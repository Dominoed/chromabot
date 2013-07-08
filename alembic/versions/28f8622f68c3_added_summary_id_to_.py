"""Added summary_id to SkirmishAction

Revision ID: 28f8622f68c3
Revises: 391058ac6f40
Create Date: 2013-07-07 16:05:54.554858

"""

# revision identifiers, used by Alembic.
revision = '28f8622f68c3'
down_revision = '391058ac6f40'

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    eval("upgrade_%s" % engine_name)()


def downgrade(engine_name):
    eval("downgrade_%s" % engine_name)()





def upgrade_engine1():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('skirmish_actions', sa.Column('summary_id', sa.String(), nullable=True))
    ### end Alembic commands ###


def downgrade_engine1():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('skirmish_actions', 'summary_id')
    ### end Alembic commands ###


def upgrade_engine2():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('skirmish_actions', sa.Column('summary_id', sa.String(), nullable=True))
    ### end Alembic commands ###


def downgrade_engine2():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('skirmish_actions', 'summary_id')
    ### end Alembic commands ###


def upgrade_engine3():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('skirmish_actions', sa.Column('summary_id', sa.String(), nullable=True))
    ### end Alembic commands ###


def downgrade_engine3():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('skirmish_actions', 'summary_id')
    ### end Alembic commands ###

