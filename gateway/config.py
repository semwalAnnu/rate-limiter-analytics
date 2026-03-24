from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "request_events"
    timescale_url: str = "postgresql://metrics_user:metrics_pass@localhost:5432/metrics"
    rate_limit_capacity: float = 100.0
    rate_limit_refill_rate: float = 10.0  # tokens per second
    jwt_secret: str = "change-me-in-production"
    upstream_url: str = "http://localhost:8001"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
