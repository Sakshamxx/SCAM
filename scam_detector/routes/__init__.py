from scam_detector.routes.auth_routes import register_auth_routes
from scam_detector.routes.main_routes import register_main_routes
from scam_detector.routes.analyze_routes import register_analyze_routes
from scam_detector.routes.offer_letter_routes import register_offer_letter_routes
from scam_detector.routes.verify_routes import register_verify_routes

def register_all_routes(app):
    register_auth_routes(app)
    register_main_routes(app)
    register_analyze_routes(app)
    register_offer_letter_routes(app)
    register_verify_routes(app)
