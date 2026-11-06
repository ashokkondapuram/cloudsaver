from app.analysis_service.evaluators import cost, operational, performance, reliability, security

EVALUATORS = (
    cost.evaluate,
    performance.evaluate,
    reliability.evaluate,
    security.evaluate,
    operational.evaluate,
)
