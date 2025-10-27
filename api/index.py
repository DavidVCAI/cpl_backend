from mangum import Mangum
from app.main import app

# Wrap FastAPI app with Mangum for serverless deployment
handler = Mangum(app, lifespan="off")
