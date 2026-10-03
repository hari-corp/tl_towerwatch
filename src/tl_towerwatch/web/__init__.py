from fastapi import FastAPI
from tl_towerwatch.web.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="tl_towerwatch")
    app.include_router(router)
    return app