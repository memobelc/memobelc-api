import jwt
from datetime import datetime, timedelta, timezone
from flask import current_app, jsonify
from flask_mail import Message
from werkzeug.security import generate_password_hash, check_password_hash
from base64 import urlsafe_b64encode, urlsafe_b64decode
from werkzeug.exceptions import BadRequest, Unauthorized
from src.app import mail
from src.app.models.user_model import UserModel
from src.app.models.classroom_model import ClassroomModel
from src.app.models.push_notification_model import PushNotificationModel
from src.app.config import Config


class AuthService:
    """Handles user authentication, including registration, login, and token management."""

    @staticmethod
    def create_user(name, email, password, invite_code=None):
        """Creates a new user and returns an authentication token."""
        if UserModel.find_by_email(email):
            return jsonify({"message": "User already exists!"}), 409

        hashed_password = generate_password_hash(password)
        UserModel(name=name, email=email, password=hashed_password).save_to_db()

        user = UserModel.find_by_email(email)
        if user:
            # Se houver código de convite, processa o convite
            if invite_code:
                from src.app.models.invite_model import InviteModel
                # Verifica se o convite é válido
                invite = InviteModel.get_invite_by_code(invite_code)
                if invite and invite['status'] == 'pending':
                    # Aceita o convite
                    InviteModel.accept_invite(invite_code, str(user._id), email)
            
            # Sempre verifica se há convite por email pendente
            from src.app.models.invite_model import InviteModel
            InviteModel.update_invite_status_by_email(email)
            
            token = jwt.encode(
                {
                    "_id": user._id,
                    "email": user.email,
                    "exp": datetime.now(timezone.utc) + timedelta(hours=72),
                },
                current_app.config["SECRET_KEY"],
                algorithm="HS256",
            )
            AuthService.send_confirm_email(email, UserModel.generate_code(email))
            return jsonify({"message": "User created successfully", "token": token}), 201

        return BadRequest(description="An error has occurred!")

    @staticmethod
    def authenticate_user(email, password):
        """Authenticates a user and returns an access token."""
        user = UserModel.find_by_email(email)
        if user and check_password_hash(user.password, password):
            is_confirmed = UserModel.verify_is_confirmed(user.email)
            
            if not is_confirmed:
                AuthService.send_confirm_email(email, UserModel.generate_code(email))
            expiration = timedelta(hours=72 if is_confirmed else 0.25)

            token = jwt.encode(
                {
                    "_id": str(user._id),
                    "email": user.email,
                    "exp": datetime.now(timezone.utc) + expiration,
                },
                current_app.config["SECRET_KEY"],
                algorithm="HS256",
            )

            if is_confirmed:
                return {
                    "token": str(token) if not isinstance(token, str) else token,
                    "name": user.name,
                    "email": user.email,
                    "user_id": str(user._id),
                    "role": user.role,
                    "roles": user.get_roles(),
                    "must_change_password": bool(getattr(user, "must_change_password", False)),
                }
            else:
                return {"pending": ["User not confirmed!", str(token) if not isinstance(token, str) else token]}

        return None

    @staticmethod
    def issue_auth_token(user, hours=72):
        token = jwt.encode(
            {
                "_id": str(user._id),
                "email": user.email,
                "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
            },
            current_app.config["SECRET_KEY"],
            algorithm="HS256",
        )
        return {
            "token": str(token) if not isinstance(token, str) else token,
            "name": user.name,
            "email": user.email,
            "user_id": str(user._id),
            "role": user.role,
            "roles": user.get_roles(),
            "must_change_password": bool(getattr(user, "must_change_password", False)),
        }

    @staticmethod
    def verify_code(user, code):
        """Verifies a user's validation code and confirms their account."""
        if UserModel.verify_code(user.email, code):
            UserModel.turn_confirmed(user.email)
            
            classrooms = UserModel.verify_user_is_guest(user._id)
            
            if len(classrooms) > 0:
                for classroom in classrooms:
                    ClassroomModel.add_students(classroom.get('_id'), user._id)
                    ClassroomModel.remove_user_guest(classroom.get('_id'), user.email)
            return True
        return False

    @staticmethod
    def refresh_token(token):
        """Refreshes the authentication token."""
        try:
            data = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
            user = UserModel.find_by_email(data["email"])

            if user:
                token = jwt.encode(
                    {
                        "_id": str(user._id),
                        "email": user.email,
                        "exp": datetime.now(timezone.utc) + timedelta(hours=72),
                    },
                    current_app.config["SECRET_KEY"],
                    algorithm="HS256",
                )
                return {
                    "token": token,
                    "name": user.name,
                    "email": user.email,
                    "user_id": str(user._id),
                    "role": user.role,
                    "roles": user.get_roles(),
                    "must_change_password": bool(getattr(user, "must_change_password", False)),
                }

        except jwt.ExpiredSignatureError:
            return None

        return None

    @staticmethod
    def send_confirm_email(email, code):
        """Sends a confirmation email with a verification code."""
        msg = Message("Account Verification", recipients=[email])
        msg.body = f"Your verification code is: {code}"
        mail.send(msg)
        return "Email sent!"

    @staticmethod
    def forgot_password(email):
        """Handles password recovery by sending a verification code via email."""
        user = UserModel.find_by_email(email.lower())
        if not user:
            return None

        # Gera um código de 6 dígitos e salva no banco
        reset_code = UserModel.generate_reset_code(email.lower())
        
        try:
            msg = Message("Recuperação de senha", recipients=[email.lower()])
            msg.body = f"Olá!\n\nSeu código de recuperação de senha é: {reset_code}\n\nEste código é válido por 15 minutos.\n\nSe você não solicitou isso, ignore este e-mail."
            mail.send(msg)
            
            return {"message": "Código de recuperação enviado com sucesso para seu e-mail."}
        except Exception as e:
            # Log do erro para debug, mas não expõe detalhes ao usuário
            current_app.logger.error(f"Erro ao enviar email de recuperação de senha: {str(e)}")
            # Retorna sucesso mesmo se o email falhar (por segurança, não revela se o email existe)
            # O código foi gerado e salvo, então o usuário pode tentar usar mesmo se o email não foi enviado
            return {"message": "Código de recuperação gerado. Verifique seu e-mail."}

    @staticmethod
    def verify_reset_code(email, code):
        """Verifica se o código de recuperação é válido."""
        try:
            email_lower = email.lower().strip()
            code_str = str(code).strip()
            
            user = UserModel.find_by_email(email_lower)
            if not user:
                current_app.logger.warning(f"Usuário não encontrado para email: {email_lower}")
                return False
            
            # Busca os dados do código de reset através do model
            reset_data = UserModel.get_reset_code_data(email_lower)
            if not reset_data:
                current_app.logger.warning(f"Dados do código de reset não encontrados para email: {email_lower}")
                return False
            
            stored_code = reset_data.get('reset_code')
            code_expiry = reset_data.get('reset_code_expiry')
            
            if not stored_code:
                current_app.logger.warning(f"Código de reset não encontrado para email: {email_lower}")
                return False
            
            if not code_expiry:
                current_app.logger.warning(f"Expiração do código não encontrada para email: {email_lower}")
                return False
            
            # Verifica se o código expirou
            # Garante que ambas as datas tenham timezone para comparação
            now = datetime.now(timezone.utc)
            
            # MongoDB pode retornar datetime como naive ou aware
            if isinstance(code_expiry, datetime):
                # Se code_expiry não tem timezone (naive), assume UTC
                if code_expiry.tzinfo is None:
                    code_expiry = code_expiry.replace(tzinfo=timezone.utc)
                else:
                    # Se já tem timezone, converte para UTC para comparação
                    code_expiry = code_expiry.astimezone(timezone.utc)
            else:
                # Se não é datetime, tenta converter
                current_app.logger.error(f"code_expiry não é datetime: {type(code_expiry)}")
                return False
            
            if now > code_expiry:
                current_app.logger.warning(f"Código expirado para email: {email_lower}. Agora: {now}, Expira: {code_expiry}")
                return False
            
            # Converte ambos para string para comparação
            stored_code_str = str(stored_code).strip()
            
            # Verifica se o código está correto
            is_valid = stored_code_str == code_str
            if not is_valid:
                current_app.logger.warning(f"Código inválido. Esperado: {stored_code_str}, Recebido: {code_str}")
            
            return is_valid
        except Exception as e:
            current_app.logger.error(f"Erro ao verificar código de reset: {str(e)}")
            return False
    
    @staticmethod
    def change_password(user, current_password, new_password):
        if not current_password or not new_password:
            return {"error": "Current and new password are required"}, 400
        if len(new_password) < 6:
            return {"error": "Password must be at least 6 characters"}, 400
        if not check_password_hash(user.password, current_password):
            return {"error": "Invalid current password"}, 401
        if current_password == new_password:
            return {"error": "New password must be different"}, 400
        cpf_digits = "".join(ch for ch in str(getattr(user, "cpf_cnpj") or "") if ch.isdigit())
        if cpf_digits and new_password.strip() == cpf_digits:
            return {"error": "New password cannot be your CPF"}, 400
        hashed = generate_password_hash(new_password)
        UserModel.update_password(str(user._id), hashed)
        updated = UserModel.find_by_id(user._id)
        return AuthService.issue_auth_token(updated or user), 200

    @staticmethod
    def reset_password(email, code, new_password):
        """Redefine a senha usando email e código de verificação."""
        # Verifica o código primeiro
        if not AuthService.verify_reset_code(email, code):
            return jsonify({"error": "Código inválido ou expirado."}), 400
        
        user = UserModel.find_by_email(email.lower())
        if not user:
            return jsonify({"error": "Usuário não encontrado."}), 404
        
        hashed_password = generate_password_hash(new_password)
        response = UserModel.update_password(str(user._id), hashed_password)
        
        if response:
            # Remove o código de reset após uso bem-sucedido através do model
            UserModel.remove_reset_code(email.lower())
            return jsonify({"message": "Senha atualizada com sucesso!"}), 200
        
        return jsonify({"error": "Erro ao atualizar a senha."}), 500
        
        
    @staticmethod
    def save_user_access_log(data):
        response = UserModel.save_user_access_log(data)
        return response

    @staticmethod
    def mail_list(name, email):
        response = UserModel.mail_list(name, email)
        if response:
            return jsonify(""), 200

    @staticmethod
    def logout_user(user_id: str):
        """Remove tokens de push do usuário ao fazer logout para não receber mais notificações no dispositivo."""
        PushNotificationModel.remove_tokens_by_user(user_id)
        return True
