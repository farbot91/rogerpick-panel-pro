import json
import os
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, BigInteger, Text, Float
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

DB_USER='farbod'
DB_PASSWORD='farbod'
DB_HOST='localhost'
DB_NAME='mydatabase'

BASE_DIR = Path(__file__).resolve().parent


def load_database_url():
    if os.environ.get('DATABASE_URL'):
        return os.environ['DATABASE_URL']
    settings_path = Path(os.environ.get('WEB_PANEL_SETTINGS', BASE_DIR / 'web_panel_settings.json'))
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding='utf-8'))
            if settings.get('database_url'):
                return settings['database_url']
        except Exception:
            pass
    return f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'

# Create the engine and connect to the MySQL database
DATABASE_URL = load_database_url()
engine_kwargs = {'echo': False}
if not DATABASE_URL.startswith('sqlite'):
    engine_kwargs.update({'pool_size': 20, 'max_overflow': 40})
engine = create_engine(DATABASE_URL, **engine_kwargs)

# Create a base class for declarative class definitions
Base = declarative_base()

# Create a session factory
Session = sessionmaker(bind=engine)

# Define the User table
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True)
    balance = Column(Integer)
    inviter_id = Column(Integer, ForeignKey('users.id'))
    purchases = Column(Integer, default=0)
    web_password_hash = Column(String(255))
    is_blocked = Column(Boolean, default=False)

    # Relationship to Subscription table
    subscriptions = relationship("Subscription", back_populates="user")
    invited_users = relationship("User", back_populates="inviter", remote_side=[id])
    inviter = relationship("User", back_populates="invited_users")


# Define the Subscription table
class Subscription(Base):
    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    link = Column(String(255))
    gigabytes = Column(Integer)
    links = Column(Text)
    is_active = Column(Boolean, default=True)
    
    # Foreign key to User table
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User", back_populates="subscriptions")

    # Relationship to Config table
    configs = relationship("Config", back_populates="subscription")


# Define the Waitlist table
class Waitlist(Base):
    __tablename__ = 'waitlist'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    price = Column(Integer)
    gigabytes = Column(Integer)
    message = Column(String(255))
    receipt_image_path = Column(String(255))
    status = Column(String(32), default='pending')
    created_at = Column(String(32))
    reviewed_at = Column(String(32))

class BalanceTransfer(Base):
    __tablename__ = 'balance_transfers'

    id = Column(Integer, primary_key=True)
    source_tg_id = Column(BigInteger)
    destination_tg_id = Column(BigInteger)
    gigabytes = Column(Integer)
    created_at = Column(String(32))

class Config(Base):
    __tablename__ = 'configs'

    id = Column(Integer, primary_key=True)
    client_uuid = Column(String(255))
    client_email = Column(String(255))
    link = Column(String(2047))
    down = Column(Float, default=0)
    up = Column(Float, default=0)

    # Foreign key to Subscription and Server tables
    subscription_id = Column(Integer, ForeignKey('subscriptions.id'))
    server_id = Column(Integer, ForeignKey('servers.id'))

    subscription = relationship("Subscription", back_populates="configs")
    server = relationship("Server", back_populates="configs")

class Server(Base):
    __tablename__ = 'servers'

    id = Column(Integer, primary_key=True)
    port = Column(Integer)
    inbound_id = Column(Integer)
    domain = Column(String(255))
    username = Column(String(255))
    password = Column(String(255))
    country = Column(String(255))
    is_vless = Column(Boolean)
    pub_key = Column(String(255))
    private_key = Column(String(255))
    sni = Column(String(255))
    domain_name = Column(String(255))
    is_tcp = Column(Boolean)
    protocol = Column(String(64))
    network = Column(String(64))
    security = Column(String(64))
    inbound_settings_json = Column(Text)
    stream_settings_json = Column(Text)
    sniffing_json = Column(Text)
    client_template_json = Column(Text)
    

    # Relationship to Config table
    configs = relationship("Config", back_populates="server")

# Create the tables in the database
Base.metadata.create_all(engine)

def ensure_schema_updates():
    inspector = inspect(engine)
    user_columns = {column['name'] for column in inspector.get_columns('users')}
    if 'web_password_hash' not in user_columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE users ADD COLUMN web_password_hash VARCHAR(255)'))
    if 'is_blocked' not in user_columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0'))
    server_columns = {column['name'] for column in inspector.get_columns('servers')}
    server_updates = {
        'protocol': 'ALTER TABLE servers ADD COLUMN protocol VARCHAR(64)',
        'network': 'ALTER TABLE servers ADD COLUMN network VARCHAR(64)',
        'security': 'ALTER TABLE servers ADD COLUMN security VARCHAR(64)',
        'inbound_settings_json': 'ALTER TABLE servers ADD COLUMN inbound_settings_json TEXT',
        'stream_settings_json': 'ALTER TABLE servers ADD COLUMN stream_settings_json TEXT',
        'sniffing_json': 'ALTER TABLE servers ADD COLUMN sniffing_json TEXT',
        'client_template_json': 'ALTER TABLE servers ADD COLUMN client_template_json TEXT',
    }
    missing_updates = [sql for name, sql in server_updates.items() if name not in server_columns]
    if missing_updates:
        with engine.begin() as connection:
            for sql in missing_updates:
                connection.execute(text(sql))
    waitlist_columns = {column['name'] for column in inspector.get_columns('waitlist')}
    if 'receipt_image_path' not in waitlist_columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE waitlist ADD COLUMN receipt_image_path VARCHAR(255)'))
    waitlist_updates = {
        'status': "ALTER TABLE waitlist ADD COLUMN status VARCHAR(32) DEFAULT 'pending'",
        'created_at': 'ALTER TABLE waitlist ADD COLUMN created_at VARCHAR(32)',
        'reviewed_at': 'ALTER TABLE waitlist ADD COLUMN reviewed_at VARCHAR(32)',
    }
    missing_waitlist_updates = [sql for name, sql in waitlist_updates.items() if name not in waitlist_columns]
    if missing_waitlist_updates:
        with engine.begin() as connection:
            for sql in missing_waitlist_updates:
                connection.execute(text(sql))

ensure_schema_updates()


