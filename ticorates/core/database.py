from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = "sqlite:///ticorates.db"

engine = create_engine(DATABASE_URL)


def create_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
