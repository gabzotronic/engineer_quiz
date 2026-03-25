from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.db import init_db, get_db
from src.routes import home, quiz, results

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Auto-seed if database is empty (e.g. fresh Railway deploy)
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM questions")
        row = await cursor.fetchone()
        if row[0] == 0:
            from cli.seed import seed
            await seed()
    finally:
        await db.close()
    yield


app = FastAPI(title="Engineer Quiz", lifespan=lifespan)

app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(home.router)
app.include_router(quiz.router)
app.include_router(results.router)
