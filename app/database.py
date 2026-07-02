from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import DATABASE_URL

# Create PostgreSQL database engine
engine = create_engine(DATABASE_URL)

# Configure database session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base class for models
Base = declarative_base()

# Dependency utility for routes to acquire database sessions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
