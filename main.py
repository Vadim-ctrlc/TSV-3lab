import os

from fastapi import FastAPI, Depends, Path, HTTPException, status
from contextlib import asynccontextmanager

from typing import Optional, Annotated

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio.session import async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import select

from pydantic import BaseModel, ConfigDict


engine = create_async_engine(
    "sqlite+aiosqlite:///tasks.db"
)


new_session = async_sessionmaker(engine, expire_on_commit=False)


class Model(DeclarativeBase):
    pass


class TaskOrm(Model):
    """ORM-модель задачи, таблица `tasks`."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[Optional[str]]


async def create_tables():
    """Создать все таблицы, описанные в метаданных ORM-моделей."""
    async with engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)


async def delete_tables():
    """Удалить все таблицы, описанные в метаданных ORM-моделей."""
    async with engine.begin() as conn:
        await conn.run_sync(Model.metadata.drop_all)


class STaskAdd(BaseModel):
    """Схема данных для создания новой задачи."""
    name: str
    description: Optional[str] = None


class STaskUpdate(BaseModel):
    """Схема данных для частичного обновления задачи."""
    name: Optional[str] = None
    description: Optional[str] = None


class STask(STaskAdd):
    """Схема задачи в том виде, в котором она отдаётся клиенту."""
    model_config = ConfigDict(from_attributes=True)
    id: int


class TaskTepository:
    @classmethod
    async def add_one(cls, data: STaskAdd) -> int:
        """Добавить новую задачу в базу.

        Args:
            data: Валидированные данные новой задачи.

        Returns:
            int: Идентификатор созданной задачи.
        """
        async with new_session() as session:
            task_dict = data.model_dump()

            task = TaskOrm(**task_dict)
            session.add(task)
            await session.flush()
            new_id = task.id
            await session.commit()
            return new_id

    @classmethod
    async def find_all(cls) -> list[STask]:
        """Вернуть список всех задач из базы.

        Returns:
            list[STask]: Все задачи (пустой список, если таблица пуста).
        """
        async with new_session() as session:
            query = select(TaskOrm)
            result = await session.execute(query)
            task_models = result.scalars().all()
            task_schemas = [STask.model_validate(task_model) for task_model in task_models]
            return task_schemas

    @classmethod
    async def delete_task(cls, task_id: int) -> STask | None:
        """Удалить задачу по идентификатору.

        Args:
            task_id: Уникальный идентификатор задачи.

        Returns:
            STask | None: Удалённая запись или None, если задачи с таким ID нет.
        """
        async with new_session() as session:
            task = await session.get(TaskOrm, task_id)
            if task is None:
                return None
            await session.delete(task)
            await session.commit()
            return STask.model_validate(task)

    @classmethod
    async def update_task(cls, task_id: int, data: STaskUpdate) -> STask | None:
        """Частично обновить задачу по идентификатору.

        Args:
            task_id: Уникальный идентификатор задачи.
            data: Новые значения полей (можно передать только часть).

        Returns:
            STask | None: Обновлённая запись или None, если задачи с таким ID нет.
        """
        async with new_session() as session:
            task = await session.get(TaskOrm, task_id)
            if task is None:
                return None
            update_dict = data.model_dump(exclude_unset=True)
            for key, val in update_dict.items():
                setattr(task, key, val)
            await session.commit()
            return STask.model_validate(task)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    if not os.path.exists("./tasks.db"):
        await create_tables()
        print("DB created")
    yield
    print("Shutting down")


app = FastAPI(lifespan=lifespan)


@app.post("/tasks")
async def add_task(task: Annotated[STaskAdd, Depends()]) -> int:
    """Создать новую задачу.

    Args:
        task: Название и описание задачи (передаются через query-параметры).

    Returns:
        int: Идентификатор созданной задачи.
    """
    task_id = await TaskTepository.add_one(task)
    return task_id


@app.get("/tasks")
async def get_tasks() -> list[STask]:
    """Получить список всех задач.

    Returns:
        list[STask]: Все задачи из базы.
    """
    tasks = await TaskTepository.find_all()
    return tasks


@app.delete("/tasks")
async def delete_task(task_id: int) -> STask:
    """Удалить задачу по идентификатору.

    Args:
        task_id: Идентификатор задачи.

    Returns:
        STask: Удалённая запись.

    Raises:
        HTTPException: 404, если задача с таким ID не найдена.
    """
    removed_task = await TaskTepository.delete_task(task_id)
    if removed_task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failed to delete task! ID not found..."
        )
    return STask.model_validate(removed_task)


@app.patch("/tasks/{task_id}")
async def edit_task(task_id: Annotated[int, Path(gt=0)],
                    task_data: STaskUpdate) -> STask:
    """Частично обновить задачу по идентификатору.

    Args:
        task_id: Идентификатор задачи, строго больше 0.
        task_data: Новые значения полей.

    Returns:
        STask: Обновлённая запись.

    Raises:
        HTTPException: 404, если задача не найдена;
            422, если task_id <= 0 или тело запроса невалидно.
    """
    task = await TaskTepository.update_task(task_id, task_data)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failed to update task! ID not found..."
        )

    return STask.model_validate(task)


def main():
    pass


if __name__ == "__main__":
    main()
