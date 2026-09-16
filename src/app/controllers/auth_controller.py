from flask import Blueprint, jsonify, request, current_app
from src.app.services.auth_service import AuthService
from src.app.middlewares.token_required import token_required


class AuthController:
    """Handles user authentication operations, including registration, login, token refresh, and code verification."""

    @staticmethod
    def register():
        """Registers a new user and returns a token upon success."""
        data = request.get_json()
        if not data or not all(k in data for k in ["email", "password", "name"]):
            return jsonify({"error": "Missing required information"}), 400

        invite_code = data.get("invite_code")  # Opcional: código de convite
        token = AuthService.create_user(data["name"], data["email"].lower(), data["password"], invite_code)
        return token

    @staticmethod
    def login():
        """Authenticates a user and returns an access token."""
        data = request.get_json()
        if not data or "email" not in data or "password" not in data:
            return jsonify({"error": "Email and password are required"}), 400

        try:
            result = AuthService.authenticate_user(data["email"].lower(), data["password"])
            if result:
                return jsonify(result), 200
            return jsonify({"error": "Invalid credentials"}), 401
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @staticmethod
    def refresh_token():
        """Refreshes the authentication token."""
        data = request.get_json()
        if not data or "token" not in data:
            return jsonify({"error": "Token is required"}), 400

        token = AuthService.refresh_token(data["token"])
        if token:
            return jsonify(token), 200

        return jsonify({"error": "Invalid credentials"}), 401
                                                                                                                                                                                                                                                                                                                                                                
    @staticmethod
    @token_required
    def verify_code(current_user, token):
        """Verifies the user's validation code and refreshes the token if valid."""
        data = request.get_json()
        if not data or "code" not in data:
            return jsonify({"error": "Code is required"}), 400

        if AuthService.verify_code(current_user, data["code"]):
            token = AuthService.refresh_token(token)
            return jsonify(token), 200

        return jsonify({"error": "Invalid code"}), 401

    @staticmethod
    def forgot_password():
        """Handles password recovery requests."""
        data = request.get_json()
        if "email" not in data:
            return jsonify({"error": "Email is required"}), 400

        try:
            response = AuthService.forgot_password(data["email"])
            if response:
                return jsonify(response), 200
            # Por segurança, não revela se o email existe ou não
            return jsonify({"message": "Se o email existir, um código de recuperação foi enviado."}), 200
        except Exception as e:
            current_app.logger.error(f"Erro no forgot_password: {str(e)}")
            # Por segurança, retorna sucesso mesmo em caso de erro
            return jsonify({"message": "Se o email existir, um código de recuperação foi enviado."}), 200
    
    @staticmethod
    def verify_reset_code():
        """Verifica se o código de recuperação é válido."""
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        if 'code' not in data:
            return jsonify({"error": "Código é obrigatório"}), 400
        
        if 'email' not in data:
            return jsonify({"error": "Email é obrigatório"}), 400
        
        try:
            email = data['email'].lower().strip() if isinstance(data['email'], str) else str(data['email']).lower().strip()
            code = str(data['code']).strip()
            
            is_valid = AuthService.verify_reset_code(email, code)
            if is_valid:
                return jsonify({"message": "Código válido", "valid": True}), 200
            return jsonify({"error": "Código inválido ou expirado", "valid": False}), 400
        except Exception as e:
            current_app.logger.error(f"Erro ao verificar código de reset: {str(e)}")
            return jsonify({"error": f"Erro ao verificar código: {str(e)}", "valid": False}), 400
    
    @staticmethod
    def reset_password():
        data = request.get_json()
        
        if not data or "password" not in data or 'code' not in data or 'email' not in data:
            return jsonify({"error": "Email, code and password are required"}), 400
        
        try:
            response = AuthService.reset_password(data['email'], data['code'], data['password'])
            return response
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    
    @staticmethod
    def save_user_access_log():
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        try:
            response = AuthService.save_user_access_log(data)
            if response:
                return jsonify({"message": "Access log saved successfully"}), 200
            return jsonify({"error": "User ID is required"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    @staticmethod
    def mail_list():
            
        data = request.get_json()
        if not data or not all(k in data for k in ["email"]):
            return jsonify({"error": "Missing required information"}), 400
        
        if "name" in data:
            name = data["name"]
        else:
            name = ''

        response = AuthService.mail_list(name, data["email"].lower())
        return response

    @staticmethod
    @token_required
    def change_password(current_user, token):
        data = request.get_json() or {}
        payload, status = AuthService.change_password(
            current_user,
            data.get("current_password") or data.get("password") or "",
            data.get("new_password") or "",
        )
        return jsonify(payload), status

    @staticmethod
    @token_required
    def logout(current_user, token):
        """Logout lógico da API: remove tokens de push do usuário para não receber notificações."""
        AuthService.logout_user(str(current_user._id))
        return jsonify({"message": "Logged out successfully"}), 200


auth_blueprint = Blueprint("auth_blueprint", __name__)

auth_blueprint.route("/register", methods=["POST"])(AuthController.register)
auth_blueprint.route("/login", methods=["POST"])(AuthController.login)
auth_blueprint.route("/refresh_token", methods=["POST"])(AuthController.refresh_token)
auth_blueprint.route("/verify_code", methods=["POST"])(AuthController.verify_code)
auth_blueprint.route("/forgot_password", methods=["POST"])(AuthController.forgot_password)
auth_blueprint.route("/verify_reset_code", methods=["POST"])(AuthController.verify_reset_code)
auth_blueprint.route("/reset_password", methods=["PUT"])(AuthController.reset_password)
auth_blueprint.route("/access_log", methods=['POST'])(AuthController.save_user_access_log)
auth_blueprint.route("/mail_list", methods=["POST"])(AuthController.mail_list)
auth_blueprint.route("/change_password", methods=["PUT"])(AuthController.change_password)
auth_blueprint.route("/logout", methods=["POST"])(AuthController.logout)
