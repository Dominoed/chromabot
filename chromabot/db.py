import json
import logging
import time

from sqlalchemy import (
    create_engine, Boolean, Column, ForeignKey, Integer, String, Table)
from sqlalchemy.orm import backref, relationship, sessionmaker
from sqlalchemy.orm.session import Session
from sqlalchemy.ext.declarative import declarative_base


# Some helpful model exceptions

class InsufficientException(Exception):
    def __init__(self, requested, available, ofwhat):
        Exception.__init__(self,
                           "Insufficient %s - needed %d but only had %d" %
                           (ofwhat, requested, available))
        self.requested = requested
        self.available = available
        self.ofwhat = ofwhat


class NonAdjacentException(Exception):
    def __init__(self, src, dest):
        Exception.__init__(self,
                           "%s and %s are not adjacent!" % (src, dest))


class InProgressException(Exception):
    def __init__(self, other):
        self.other = other
        Exception.__init__(self, "You're already doing that!")


class TeamException(Exception):
    def __init__(self, what, friendly=False):
        self.friendly = friendly
        self.what = what
        if friendly:
            msg = "%s is friendly!" % what
        else:
            msg = "%s is not friendly!" % what
        Exception.__init__(self, msg)


class RankException(Exception):
    def __init__(self):
        Exception.__init__(self,
                           "You do not have the rank required to do that!")


class Model(object):

    def session(self):
        return Session.object_session(self)

    def timestr(self, secs=None):
        if secs is None:
            secs = time.mktime(time.localtime())
        return time.strftime("%Y-%m-%d %H:%M:%S GMT",
                              time.gmtime(secs))

Base = declarative_base(cls=Model)


class DB(object):
    def __init__(self, config):
        self.engine = create_engine(config.dbstring, echo=False)
        self.sessionfactory = sessionmaker(bind=self.engine)

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def drop_all(self):
        Base.metadata.drop_all(self.engine)

    def session(self):
        return self.sessionfactory()


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    team = Column(Integer)
    loyalists = Column(Integer)
    committed_loyalists = Column(Integer, default=0)
    region_id = Column(Integer, ForeignKey('regions.id'))
    leader = Column(Boolean, default=False)

    def __repr__(self):
        return "<User(name='%s', team='%d', loyalists='%d')>" % (
            self.name, self.team, self.loyalists)

    @property
    def rank(self):
        if self.leader:
            return "general"
        else:
            return "captain"

    def is_moving(self):
        if self.movement:
            return self.movement[0]
        return None

    def move(self, how_many, where, delay):
        result = None
        sess = Session.object_session(self)

        already = sess.query(MarchingOrder).filter_by(leader=self).first()
        if already:
            raise InProgressException(already)

        if how_many > self.loyalists:
            # TODO: Attempt to pick up loyalists
            raise InsufficientException(how_many, self.loyalists, "loyalists")

        # TODO: Drop off loyalists
        if not where in self.region.borders:
            raise NonAdjacentException(self.region, where)

        if where.owner != self.team:
            if not where.battle:
                raise TeamException(where)

        if(delay > 0):
            result = MarchingOrder(arrival=time.mktime(time.localtime())
                                    + delay,
                                   leader=self,
                                   source=self.region,
                                   dest=where)
            sess.add(result)
        else:
            self.region = where
        # TODO: Change number of loyalists
        sess.commit()

        return result

region_to_region = Table("region_to_region", Base.metadata,
        Column("left_id", Integer, ForeignKey("regions.id"), primary_key=True),
        Column("right_id", Integer, ForeignKey("regions.id"),
               primary_key=True))


class MarchingOrder(Base):
    __tablename__ = "marching_orders"

    id = Column(Integer, primary_key=True)
    arrival = Column(Integer, default=0)

    leader_id = Column(Integer, ForeignKey('users.id'))
    leader = relationship("User", backref="movement")

    # Relationships for these defined in the Region class
    source_id = Column(Integer, ForeignKey("regions.id"))
    dest_id = Column(Integer, ForeignKey("regions.id"))

    @classmethod
    def update_all(cls, sess):
        orders = sess.query(cls).all()
        result = []
        for order in orders:
            if order.update():
                result.append(order)
        return result

    def has_arrived(self):
        now = time.mktime(time.localtime())
        return self.arrival <= now

    def arrival_str(self):
        return self.timestr(self.arrival)

    def update(self):
        sess = Session.object_session(self)
        if self.has_arrived():
            self.leader.region = self.dest
            sess.delete(self)
            sess.commit()
            return True
        return False


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    srname = Column(String(255))
    capital = Column(Integer)
    owner = Column(Integer)

    people = relationship("User", backref="region")

    borders = relationship("Region", secondary=region_to_region,
        primaryjoin=id == region_to_region.c.left_id,
        secondaryjoin=id == region_to_region.c.right_id,
        cascade="all, delete",
        backref="other_borders")

    outbound_armies = relationship("MarchingOrder",
                                   foreign_keys=MarchingOrder.source_id,
                                   backref="source")

    inbound_armies = relationship("MarchingOrder",
                                  foreign_keys=MarchingOrder.dest_id,
                                  backref="dest")

    @classmethod
    def capital_for(cls, team, session):
        return session.query(cls).filter_by(capital=team).first()

    @classmethod
    def create_from_json(cls, json_str=None, json_file=None):
        if json_file is not None:
            with open(json_file) as srcfile:
                unconverted = json.load(srcfile)
        else:
            unconverted = json.loads(json_str)

        atlas = {}
        result = []
        for region in unconverted:
            capital = None
            owner = None
            if 'capital' in region:
                capital = region['capital']
                owner = capital
            if 'owner' in region:
                owner = region['owner']
            created = cls(name=region['name'].lower(),
                          srname=region['srname'].lower(),
                          capital=capital,
                          owner=owner)
            result.append(created)
            atlas[created.name] = created

        # Hook up the regions
        for region in unconverted:
            created = atlas[region['name'].lower()]
            for adjacent in region['connections']:
                created.add_border(atlas[adjacent.lower()])
        return result

    def add_border(self, other_region):
        """Adds the other region to this region's borders, and then does the
        same for the other region, to keep bidirectionality intact"""
        # So tired of trying to figure out how to tell sqlalchemy to do it,
        # just going to do it manually
        self.borders.append(other_region)
        other_region.borders.append(self)

    def invade(self, by_who, when):
        if not by_who.leader:
            raise RankException()

        if self.owner == by_who.team:
            raise TeamException(self, friendly=True)

        if self.battle:
            raise InProgressException(self.battle)

        # Make sure that the given team owns at least one region adjacent
        # to this one
        bad_neighbors = [region for region in self.borders
                         if region.owner is not None
                            and region.owner == by_who.team]
        if not bad_neighbors:
            raise NonAdjacentException(self, "your territory")

        sess = Session.object_session(self)
        battle = Battle(
            region=self,
            begins=when
            )
        sess.add(battle)
        sess.commit()
        return battle

    def markdown(self):
        return "[%s](/r/%s)" % (self.name, self.srname)

    def __repr__(self):
        return "<Region(id='%s', name='%s')>" % (self.id, self.name)


class Battle(Base):
    __tablename__ = "battles"

    id = Column(Integer, primary_key=True)
    begins = Column(Integer, default=0)
    submission_id = Column(String)

    region_id = Column(Integer, ForeignKey('regions.id'))
    region = relationship("Region", uselist=False, backref="battle")

    @classmethod
    def update_all(cls, sess):
        battles = sess.query(cls).all()
        begin = []
        ended = []
        for battle in battles:
            ready = battle.update()
            if ready:
                begin.append(battle)
            #TODO: add to ended if this has ended

        result = {
            "begin": begin,
            "ended": ended
        }
        return result

    def begins_str(self):
        return self.timestr(self.begins)

    def create_skirmish(self, who, howmany):
        sess = self.session()
        sa = SkirmishAction.create(sess, who, howmany)
        sa.battle = self
        sess.commit()
        return sa

    def has_started(self):
        """
        A battle has started if its time has come, and there's a thread
        to do battle in.
        """
        if self.is_ready():
            return self.submission_id
        return False

    def is_ready(self):
        now = time.mktime(time.localtime())
        return now >= self.begins

    def update(self):
        if self.has_started():
            # TODO: Something with this fight
            pass
        elif self.is_ready():
            return True

        return False


class SkirmishAction(Base):
    __tablename__ = "skirmish_actions"

    id = Column(Integer, primary_key=True)
    comment_id = Column(String)
    amount = Column(Integer, default=0)
    hinder = Column(Boolean, default=True)

    battle_id = Column(Integer, ForeignKey('battles.id'))
    battle = relationship("Battle", backref="skirmishes")

    participant_id = Column(Integer, ForeignKey('users.id'))
    participant = relationship("User", backref="skirmishes")

    parent_id = Column(Integer, ForeignKey('skirmish_actions.id'))
    children = relationship("SkirmishAction",
                            backref=backref('parent', remote_side=[id]))

    @classmethod
    def create(cls, sess, who, howmany, hinder=True, parent=None):
        sa = SkirmishAction(participant=who,
                            amount=howmany,
                            hinder=hinder,
                            parent=parent)
        sa.commit_if_valid()

        return sa

    def react(self, who, howmany, hinder=True):
        sess = self.session()
        sa = SkirmishAction.create(sess, who, howmany, hinder, parent=self)
        sess.commit()

        return sa

    def commit_if_valid(self):
        self.validate()

        sess = self.session()
        sess.add(self)
        sess.commit()

        self.participant.committed_loyalists += self.amount

    def validate(self):
        """Raise exceptions if this is not a valid skirmish"""
        sess = self.session()

        if self.parent:
            sameteam = self.parent.participant.team == self.participant.team
            if self.hinder == sameteam:
                sess.rollback()
                raise TeamException(self, friendly=sameteam)
        else:
            # Make sure our participant doesn't have another toplevel
            s = (sess.query(SkirmishAction).
                 filter_by(parent_id=None).
                 filter_by(participant=self.participant)).count()
            # This is '1' and not '0' because for some damn reason that query
            # will count the newly created one
            if s > 1:
                sess.rollback()
                raise InProgressException(s)

        requested = self.amount + self.participant.committed_loyalists
        available = self.participant.loyalists
        if requested > available:
            sess.rollback()
            raise InsufficientException(requested, available, "loyalists")

        if requested <= 0:
            sess.rollback()
            raise InsufficientException(1, requested, "argument")

        return self

    def __repr__(self):
        if self.battle:
            pstr = str(self.battle)
        else:
            pstr = str(self.parent)

        result = ("<SkirmishAction(participant=%s, amount=%s, "
                  "hinder=%s parent=%s)>") % (self.participant.name,
                                              self.amount,
                                              self.hinder,
                                              pstr)
        return result
