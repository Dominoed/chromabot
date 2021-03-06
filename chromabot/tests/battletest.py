# coding=utf-8

import logging
import time
import unittest

import db
from db import (Battle, Processed, SkirmishAction)
from playtest import ChromaTest
from utils import now


class TestBattle(ChromaTest):

    def setUp(self):
        ChromaTest.setUp(self)
        sapphire = self.get_region("Sapphire")

        self.sapphire = sapphire

        self.alice.region = sapphire
        self.bob.region = sapphire

        self.carol = self.create_user("carol", 0)
        self.carol.region = sapphire
        self.dave = self.create_user("dave", 1)
        self.dave.region = sapphire

        self.sess.commit()

        now = time.mktime(time.localtime())
        self.battle = sapphire.invade(self.bob, now)
        self.battle.ends = now + 60 * 60 * 24
        self.battle.submission_id = "TEST"
        self.assert_(self.battle)

        self.sess.commit()

    def test_battle_creation(self):
        """Typical battle announcement"""
        londo = self.get_region("Orange Londo")
        # For testing purposes, londo is now neutral
        londo.owner = None

        now = time.mktime(time.localtime())
        when = now + 60 * 60 * 24
        battle = londo.invade(self.alice, when)
        battle.ends = when  # Also end it then, too
        self.sess.commit()

        self.assert_(battle)

        # Unless that commit took 24 hours, the battle's not ready yet
        self.assertFalse(battle.is_ready())

        # Move the deadline back
        battle.begins = now
        self.sess.commit()

        self.assert_(battle.is_ready())

    def test_disallow_invadeception(self):
        """Can't invade if you're already invading!"""
        londo = self.get_region("Orange Londo")
        # For testing purposes, londo is now neutral
        londo.owner = None

        now = time.mktime(time.localtime())
        when = now + 60 * 60 * 24
        battle = londo.invade(self.alice, when)

        self.assert_(battle)

        with self.assertRaises(db.InProgressException):
            londo.invade(self.alice, when)

        n = (self.sess.query(db.Battle).count())
        self.assertEqual(n, 2)

    def test_disallow_nonadjacent_invasion(self):
        """Invasion must come from somewhere you control"""
        pericap = self.get_region("Periopolis")

        with self.assertRaises(db.NonAdjacentException):
            pericap.invade(self.alice, 0)
        n = (self.sess.query(db.Battle).count())
        self.assertEqual(n, 1)

    def test_disallow_friendly_invasion(self):
        """Can't invade somewhere you already control"""
        londo = self.get_region("Orange Londo")

        with self.assertRaises(db.TeamException):
            londo.invade(self.alice, 0)
        n = (self.sess.query(db.Battle).count())
        self.assertEqual(n, 1)

    def test_disallow_peon_invasion(self):
        """Must have .leader set to invade"""
        londo = self.get_region("Orange Londo")
        londo.owner = None
        self.alice.leader = False

        with self.assertRaises(db.RankException):
            londo.invade(self.alice, 0)
        n = (self.sess.query(db.Battle).count())
        self.assertEqual(n, 1)

    def test_skirmish_parenting(self):
        """Make sure I set up relationships correctly w/ skirmishes"""
        root = SkirmishAction()
        a1 = SkirmishAction()
        a2 = SkirmishAction()
        self.sess.add_all([root, a1, a2])
        self.sess.commit()

        root.children.append(a1)
        root.children.append(a2)
        self.sess.commit()

        self.assertEqual(a1.parent_id, root.id)
        self.assertEqual(a2.parent_id, root.id)

    def test_battle_skirmish_assoc(self):
        """Make sure top-level skirmishes are associated with their battles"""
        battle = self.battle

        s1 = battle.create_skirmish(self.alice, 1)
        s2 = battle.create_skirmish(self.bob, 1)

        s3 = s2.react(self.alice, 1)

        self.assertEqual(len(battle.skirmishes), 3)
        self.assertIn(s1, battle.skirmishes)
        self.assertIn(s2, battle.skirmishes)
        # s3 should inherit its battle from its parents
        self.assertIn(s3, battle.skirmishes)

        self.assertEqual(s1.battle, battle)

    def test_proper_cascade(self):
        """When a battle is deleted, everything should go with it"""
        battle = self.battle

        battle.create_skirmish(self.alice, 1)
        s2 = battle.create_skirmish(self.bob, 1)
        s2.react(self.alice, 1)

        # Make up some processed comments
        battle.processed_comments.append(Processed(id36="foo"))
        battle.processed_comments.append(Processed(id36="bar"))
        self.sess.commit()
        self.assertNotEqual(self.sess.query(Processed).count(), 0)
        self.assertNotEqual(self.sess.query(SkirmishAction).count(), 0)

        self.sess.delete(battle)
        self.sess.commit()

        # Shouldn't be any skirmishes or processed
        self.assertEqual(self.sess.query(Processed).count(), 0)
        self.assertEqual(self.sess.query(SkirmishAction).count(), 0)

    def test_get_battle(self):
        """get_battle and get_root work, right?"""
        battle = self.battle

        s1 = battle.create_skirmish(self.alice, 1)
        s2 = battle.create_skirmish(self.bob, 1)

        s3 = s2.react(self.alice, 1)

        self.assertEqual(battle, s1.get_battle())
        self.assertEqual(battle, s3.get_battle())

    def test_simple_unopposed(self):
        """Bare attacks are unopposed"""
        s1 = self.battle.create_skirmish(self.alice, 1)
        s1.resolve()
        self.assert_(s1.unopposed)

        # Should be worth 2 VP
        self.assertEqual(s1.vp, 2)

    def test_no_early_fights(self):
        """
        Even if battle thread's live, can't fight until the battle
        actually starts
        """
        self.battle.begins = now() + 60 * 60 * 12

        self.assertFalse(self.battle.is_ready())
        self.assertFalse(self.battle.has_started())

        with self.assertRaises(db.TimingException):
            self.battle.create_skirmish(self.alice, 1)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 0)

    def test_canceled_unopposed(self):
        """Attacks that have counterattacks nullified are unopposed"""
        s1 = self.battle.create_skirmish(self.alice, 1)   # Attack 1
        s1a = s1.react(self.bob, 2)                       # --Attack 2
        s1a.react(self.alice, 9)                          # ----Attack 9
        s1.resolve()
        self.assertEqual(s1.victor, self.alice.team)
        self.assert_(s1.unopposed)

        # Should be 4 VP (double the 2 it'd ordinarily be worth)
        self.assertEqual(s1.vp, 4)

    def test_not_unopposed(self):
        """If there's an attack, even if ineffective, it's opposed"""
        s1 = self.battle.create_skirmish(self.alice, 2)   # Attack 2
        s1.react(self.bob, 1)                             # --Attack 1
        s1.resolve()
        self.assertFalse(s1.unopposed)

    def test_committed_loyalists(self):
        """We're actually committing to battle, right?"""
        # Indirectly tested in test_no_adds_to_overdraw_skirmish, too
        old = self.alice.committed_loyalists
        self.battle.create_skirmish(self.alice, 5)
        self.assertEqual(old + 5, self.alice.committed_loyalists)

    def test_decommit_after_battle(self):
        """When the battle's over, we no longer commit, right?"""
        sess = self.sess
        self.battle.submission_id = "TEST"  # So update_all will work correctly

        old = self.alice.committed_loyalists
        self.battle.create_skirmish(self.alice, 5)

        # And just like that, the battle's over
        self.battle.ends = self.battle.begins
        sess.commit()

        updates = Battle.update_all(sess)
        sess.commit()

        self.assertNotEqual(len(updates['ended']), 0)
        self.assertEqual(updates["ended"][0], self.battle)

        self.assertEqual(self.alice.committed_loyalists, old)

    def test_ejection_after_battle(self):
        """We don't want the losers sticking around after the fight"""
        self.battle.submission_id = "TEST"  # So update_all will work correctly

        old_bob_region = self.bob.region
        old_alice_region = self.alice.region
        self.battle.create_skirmish(self.alice, 5)

        self.battle.ends = self.battle.begins
        self.sess.commit()

        updates = Battle.update_all(self.sess)
        self.sess.commit()
        self.assertNotEqual(len(updates['ended']), 0)
        self.assertEqual(updates["ended"][0], self.battle)

        self.assertEqual(self.battle.victor, self.alice.team)

        self.assertNotEqual(self.bob.region, self.alice.region)
        self.assertNotEqual(self.bob.region, old_bob_region)
        self.assertEqual(self.alice.region, old_alice_region)

    def test_single_toplevel_skirmish_each(self):
        """Each participant can only make one toplevel skirmish"""
        self.battle.create_skirmish(self.alice, 1)

        with self.assertRaises(db.InProgressException):
            self.battle.create_skirmish(self.alice, 1)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 1)

    def test_single_response_to_skirmish(self):
        """Each participant can only response once to a skirmishaction"""
        s1 = self.battle.create_skirmish(self.alice, 1)
        s1.react(self.bob, 1)

        with self.assertRaises(db.InProgressException):
            s1.react(self.bob, 1)

        n = (self.sess.query(db.SkirmishAction).
             count())
        self.assertEqual(n, 2)

    def test_no_last_minute_ambush(self):
        """
        Can't make toplevel attacks within the last X seconds of the battle
        """
        self.battle.lockout = 60 * 60 * 24
        with self.assertRaises(db.TimingException):
            self.battle.create_skirmish(self.alice, 1)

    def test_commit_at_least_one(self):
        """It isn't a skirmish without fighters"""
        with self.assertRaises(db.InsufficientException):
            self.battle.create_skirmish(self.alice, 0)

        with self.assertRaises(db.InsufficientException):
            self.battle.create_skirmish(self.alice, -5)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 0)

    def test_support_at_least_one(self):
        # Saw this happen in testing, not sure why, reproducing here:
        s1 = self.battle.create_skirmish(self.alice, 1)
        with self.assertRaises(db.InsufficientException):
            s1.react(self.alice, 0, hinder=False)

        n = (self.sess.query(db.SkirmishAction).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 1)

    def test_no_overdraw_skirmish(self):
        """Can't start a skirmish with more loyalists than you have"""
        with self.assertRaises(db.InsufficientException):
            self.battle.create_skirmish(self.alice, 9999999)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 0)

    def test_no_adds_to_overdraw_skirmish(self):
        """Can't commit more loyalists than you have"""
        s1 = self.battle.create_skirmish(self.alice, 99)
        with self.assertRaises(db.InsufficientException):
            s1.react(self.alice, 2, hinder=False)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 1)

    def test_stop_hitting_yourself(self):
        """Can't hinder your own team"""
        s1 = self.battle.create_skirmish(self.alice, 1)
        with self.assertRaises(db.TeamException):
            s1.react(self.alice, 1, hinder=True)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 1)

    def test_disallow_betrayal(self):
        """Can't help the opposing team"""
        s1 = self.battle.create_skirmish(self.alice, 1)
        with self.assertRaises(db.TeamException):
            s1.react(self.bob, 1, hinder=False)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 1)

    def test_disallow_absent_fighting(self):
        """Can't fight in a region you're not in"""
        londo = self.get_region("Orange Londo")
        self.alice.region = londo
        self.sess.commit()

        with self.assertRaises(db.NotPresentException):
            self.battle.create_skirmish(self.alice, 1)

        n = (self.sess.query(db.SkirmishAction).filter_by(parent_id=None).
            filter_by(participant=self.alice)).count()
        self.assertEqual(n, 0)

    def test_disallow_retreat(self):
        """Can't move away once you've begun a fight"""
        self.battle.create_skirmish(self.alice, 1)
        londo = self.get_region("Orange Londo")

        with self.assertRaises(db.InProgressException):
            self.alice.move(100, londo, 0)

        n = (self.sess.query(db.MarchingOrder).
            filter_by(leader=self.alice)).count()
        self.assertEqual(n, 0)

    def test_simple_resolve(self):
        """Easy battle resolution"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10
        s1.react(self.bob, 9)                        # --Attack 9

        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.vp, 9)

    def test_failed_attack(self):
        """Stopping an attack should award VP to the ambushers"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10
        s1.react(self.bob, 19)                       # --Attack 19

        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.vp, 10)

    def test_supply_ambush(self):
        """Taking out a 'support' should not escalate further"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)
        s2 = s1.react(self.alice, 1, hinder=False)
        s2.react(self.bob, 100)  # OVERKILL!

        # Alice still wins, though - the giant 99 margin attack is just to stop
        # reinforcements
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)

    def test_default_codeword(self):
        """Supplying an unrecognized codeword should default to 'infantry'"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1, troop_type='muppet')
        self.assertEqual(s1.troop_type, "infantry")

    def test_codeword(self):
        """Use of codewords in top-level skirmises"""
        self.assertEqual(self.sess.query(db.CodeWord).count(), 0)
        self.alice.add_codeword('muppet', 'ranged')
        self.assertEqual(self.sess.query(db.CodeWord).count(), 1)

        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1, troop_type='muppet')
        self.assertEqual(s1.troop_type, "ranged")

        self.alice.remove_codeword('muppet')
        self.assertEqual(self.sess.query(db.CodeWord).count(), 0)
        s2 = s1.react(self.alice, 1, hinder=False, troop_type='muppet')
        self.assertEqual(s2.troop_type, 'infantry')

    def test_unicodeword(self):
        self.alice.add_codeword(u'ಠ_ಠ', 'ranged')
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1, troop_type=u'ಠ_ಠ')
        self.assertEqual(s1.troop_type, "ranged")

    def test_overwrite_codeword(self):
        """Use of codewords in top-level skirmises"""
        self.assertEqual(self.sess.query(db.CodeWord).count(), 0)
        self.alice.add_codeword('muppet', 'ranged')
        self.assertEqual(self.alice.translate_codeword('muppet'), 'ranged')
        self.assertEqual(self.sess.query(db.CodeWord).count(), 1)
        self.alice.add_codeword('muppet', 'infantry')
        self.assertEqual(self.alice.translate_codeword('muppet'), 'infantry')
        self.assertEqual(self.sess.query(db.CodeWord).count(), 1)

    def test_extra_default_codeword(self):
        """Using the wrong codeword should also default to infantry"""
        self.alice.add_codeword("flugelhorn", "ranged")

        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1, troop_type='muppet')
        self.assertEqual(s1.troop_type, "infantry")

    def test_response_codeword(self):
        """Use of codewords in response skirmishes"""
        self.bob.add_codeword('muppet', 'ranged')
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)
        s2 = s1.react(self.bob, 100, troop_type='muppet')
        self.assertEqual(s2.troop_type, 'ranged')

    def test_no_cross_codewording(self):
        """Bob's codewords don't work for alice"""
        self.bob.add_codeword('muppet', 'ranged')

        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1, troop_type='muppet')
        self.assertEqual(s1.troop_type, "infantry")

    def test_complex_resolve_cancel(self):
        """Multilayer battle resolution that cancels itself out"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)  # Attack 1
        s2 = s1.react(self.alice, 1, hinder=False)  # --Support 1
        s2.react(self.bob, 10)                      # ----Attack 10
        s3 = s1.react(self.bob, 10)                 # --Attack 10
        s3.react(self.alice, 10)                    # ----Attack 10

        # Make sure the leaves cancel correctly
        s2result = s2.resolve()
        self.assert_(s2result)
        self.assertEqual(s2result.victor, self.bob.team)

        s3result = s3.resolve()
        self.assert_(s3result)
        self.assertEqual(s3result.victor, None)

        # All the supports and attacks cancel each other out, winner should
        # be alice by 1
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 1)
        # s2 has 1 die, s2react has 1 die, s3 has 10 die, s3react has 10 die
        # total = 11 each; 22 because alice ends up unopposed
        self.assertEqual(result.vp, 22)

    def test_additive_support(self):
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)   # Attack 1
        s2 = s1.react(self.alice, 19, hinder=False)  # --Support 19
        s2.react(self.alice, 1, hinder=False)        # ----Support 1
        s3 = s1.react(self.bob, 20)                  # --Attack 20
        s3.react(self.alice, 5)                      # ----Attack 5

        # s2react's support adds 1 to its parent
        # Alice gets 20 from support for total of 21, bob gets 15
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 6)

    def test_additive_attacks(self):
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)   # Attack 1
        s1.react(self.alice, 19, hinder=False)       # --Support 19
        s3 = s1.react(self.bob, 20)                  # --Attack 20
        s3.react(self.bob, 5, hinder=False)          # ----Support 5

        # s3react's support adds 5 to its parent
        # Alice gets 20 support total, bob gets 25 attack
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 5)

    def test_complex_resolve_bob(self):
        """Multilayer battle resolution that ends with bob winning"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 1)   # Attack 1
        s2 = s1.react(self.alice, 10, hinder=False)  # --Support 10
        s2.react(self.bob, 1)                        # ----Attack 1
        s3 = s1.react(self.bob, 20)                  # --Attack 20
        s3.react(self.alice, 5)                      # ----Attack 5

        # Alice will win 9 support from her support,
        # but bob will gain 15 attack from his attack
        # Final score: alice 10 vs bob 15
        # Winner:  Bob by 5
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 5)

        # s2 has 1 die, s2react has 1 die, s3 has 5 die, s3react has 5 die
        # final battle has 10 die on each side
        # alice: 5 + 1 + 10, bob: 5 + 1 + 10
        self.assertEqual(result.vp, 16)

    def test_attack_types(self):
        """Using the right type of attack can boost its effectiveness"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10 infantry
        s1.react(self.bob, 8, troop_type='cavalry')  # --Attack 8 cavalry

        # Cavalry should get a 50% bonus here, for a total of 8+4=12
        # So Bob should win by 2 despite lesser numbers
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 2)
        self.assertEqual(result.vp, 10)

        s2 = battle.create_skirmish(self.bob, 10,
                                    troop_type='cavalry')  # attack 10 cavalry
        s2.react(self.alice, 8, troop_type='ranged')       # -- oppose 8 ranged
        result = s2.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 2)
        self.assertEqual(result.vp, 10)

        s3 = battle.create_skirmish(self.carol, 10,      # Attack 10 ranged
                                    troop_type='ranged')
        s3.react(self.bob, 8)                            # -- oppose 8 infantry
        result = s3.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 2)
        self.assertEqual(result.vp, 10)

    def test_bad_attack_types(self):
        """Using the wrong type of attack can hinder its effectiveness"""
        battle = self.battle
        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10 infantry
        s1.react(self.bob, 12, troop_type='ranged')  # --Attack 12 ranged

        # Ranged should get a 50% penalty here, for a total of 12/2 = 6
        # So Alice should win by 4 despite lesser numbers
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 12)

        s2 = battle.create_skirmish(self.bob, 10,        # attack 10 ranged
                                    troop_type='ranged')
        s2.react(self.alice, 12, troop_type='cavalry')   # -- oppose 12 cavalry
        result = s2.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 12)

        s3 = battle.create_skirmish(self.carol, 10,     # Attack 10 cavalry
                                    troop_type='cavalry')
        s3.react(self.bob, 12)                          # -- oppose 12 infantry
        result = s3.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.carol.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 12)

    def test_support_types(self):
        battle = self.battle

        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10 infantry
        s1.react(self.bob, 19)                       # -- oppose 19 infantry
        s1.react(self.alice, 8,                      # -- support 8 ranged
                 troop_type="ranged", hinder=False)
        # Ranged should get a 50% support bonus here, for a total of
        # 10 + 8 + 4 = 22 - alice should win by 3
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 3)
        self.assertEqual(result.vp, 19)

        s2 = battle.create_skirmish(self.bob, 10,
                troop_type="ranged")                 # Attack 10 ranged
        s2.react(self.alice, 19,
                 troop_type="ranged")                # -- oppose 19 ranged
        s2.react(self.bob, 8,                        # -- support 8 cavalry
                 troop_type="cavalry", hinder=False)

        result = s2.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 3)
        self.assertEqual(result.vp, 19)

        s3 = battle.create_skirmish(self.carol, 10,
                troop_type="cavalry")                 # Attack 10 cavalry
        s3.react(self.bob, 19,
                 troop_type="cavalry")                # -- oppose 19 cavalry
        s3.react(self.carol, 8, hinder=False)           # -- support 8 infantry

        result = s3.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.carol.team)
        self.assertEqual(result.margin, 3)
        self.assertEqual(result.vp, 19)

    def test_bad_support_types(self):
        battle = self.battle

        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10 infantry
        s1.react(self.bob, 19)                       # -- oppose 19 infantry
        s1.react(self.alice, 10,                     # -- support 10 cavalry
                 troop_type="cavalry", hinder=False)
        # Cavalry should get a 50% support penalty here, for a total of
        # 10 + 5 = 15 - bob should win by 4
        result = s1.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 20)

        s2 = battle.create_skirmish(self.bob, 10,
                troop_type="ranged")                 # Attack 10 ranged
        s2.react(self.alice, 19,
                 troop_type="ranged")                # -- oppose 19 ranged
        s2.react(self.bob, 10, hinder=False)         # -- support 10 infantry

        result = s2.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.alice.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 20)

        s3 = battle.create_skirmish(self.carol, 10,
                troop_type="cavalry")                 # Attack 10 cavalry
        s3.react(self.bob, 19,
                 troop_type="cavalry")                # -- oppose 19 cavalry
        s3.react(self.carol, 10,
                 troop_type="ranged",
                 hinder=False)                        # -- support 10 ranged

        result = s3.resolve()
        self.assert_(result)
        self.assertEqual(result.victor, self.bob.team)
        self.assertEqual(result.margin, 4)
        self.assertEqual(result.vp, 20)

    def test_orangered_victory(self):
        """Make sure orangered victories actually count"""
        self.assertEqual(None, self.sapphire.owner)
        sess = self.sess
        self.battle.create_skirmish(self.alice, 5)

        self.battle.ends = self.battle.begins
        sess.commit()
        updates = Battle.update_all(sess)
        sess.commit()

        self.assertNotEqual(len(updates['ended']), 0)
        self.assertEqual(updates["ended"][0], self.battle)
        self.assertEqual(0, self.sapphire.owner)

    def test_full_battle(self):
        """Full battle"""
        battle = self.battle
        sess = self.sess

        oldowner = self.sapphire.owner

        # Battle should be ready and started
        self.assert_(battle.is_ready())
        self.assert_(battle.has_started())

        # Still going, right?
        self.assertFalse(battle.past_end_time())

        # Skirmish 1
        s1 = battle.create_skirmish(self.alice, 10)  # Attack 10
        s1a = s1.react(self.carol, 4, hinder=False)  # --Support 4
        s1a.react(self.bob, 3)                       # ----Attack 3
        s1.react(self.dave, 8)                       # --Attack 8
        # Winner will be team orangered, 11 VP

        # Skirmish 2
        battle.create_skirmish(self.bob, 15)         # Attack 15
        # Winner will be team periwinkle, 30 VP for unopposed

        # Skirmish 3
        s3 = battle.create_skirmish(self.carol, 10)  # Attack 10
        s3.react(self.bob, 5)                        # --Attack 5
        # Winner will be team orangered, 5 VP
        # Overall winner should be team periwinkle, 30 to 16

        # End this bad boy
        self.battle.ends = self.battle.begins
        sess.commit()
        self.assert_(battle.past_end_time())

        updates = Battle.update_all(sess)
        sess.commit()

        self.assertNotEqual(len(updates['ended']), 0)
        self.assertEqual(updates["ended"][0], battle)
        self.assertEqual(battle.victor, 1)
        self.assertEqual(battle.score0, 16)
        self.assertEqual(battle.score1, 30)

        self.assertNotEqual(oldowner, battle.region.owner)
        self.assertEqual(battle.region.owner, 1)


if __name__ == '__main__':
    unittest.main()
