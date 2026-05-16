from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, BigInteger, Text, Float
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

DB_USER='farbod'
DB_PASSWORD='farbod'
DB_HOST='localhost'
DB_NAME='mydatabase'

# Create the engine and connect to the MySQL database
engine = create_engine(f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}', echo=False, pool_size=20, max_overflow=40)

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

Base.metadata.drop_all(engine)

# Create the tables in the database
Base.metadata.create_all(engine)
