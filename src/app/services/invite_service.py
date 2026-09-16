from flask import current_app, jsonify
from flask_mail import Message
from src.app import mail
from src.app.models.invite_model import InviteModel
from src.app.models.user_model import UserModel
from src.app.services.settings_service import SettingsService
from src.app.config import Config


class InviteService:
    """Serviço para gerenciar convites de usuários"""

    @staticmethod
    def send_invite_by_email(inviter_id, email):
        """Envia um convite por email"""
        try:
            # Verifica se o email já está cadastrado
            existing_user = UserModel.find_by_email(email)
            if existing_user:
                return jsonify({"error": "Este email já está cadastrado"}), 400
            
            # Verifica se já existe um convite pendente para este email
            from src.app import mongo
            from bson import ObjectId
            existing_invite = mongo.db.invites.find_one({
                'invited_email': email.lower(),
                'status': 'pending'
            })
            if existing_invite:
                return jsonify({"error": "Já existe um convite pendente para este email"}), 400
            
            # Cria o convite
            invite_id, invite_code = InviteModel.create_invite_by_email(inviter_id, email)
            
            # Busca dados do usuário que está convidando
            inviter = UserModel.find_by_id(inviter_id)
            if not inviter:
                return jsonify({"error": "Usuário não encontrado"}), 404
            
            # Envia email
            try:
                msg = Message(
                    subject="Você foi convidado para o Memobelc!",
                    recipients=[email],
                    sender=SettingsService.get("MAIL_USERNAME")
                )
                msg.body = f"""
                Olá!

                Você foi convidado por {inviter.name} para se juntar ao Memobelc!

                Memobelc é uma plataforma incrível para aprender idiomas de forma divertida e eficiente.

                Para criar sua conta, acesse: {Config.FRONT_BASE_URL}/register?invite={invite_code}

                Ou use este código de convite ao se registrar: {invite_code}

                Esperamos você!

                Equipe Memobelc
                """
                mail.send(msg)
            except Exception as e:
                current_app.logger.error(f"Erro ao enviar email de convite: {str(e)}")
                # Continua mesmo se o email falhar
            
            return jsonify({
                "message": "Convite enviado com sucesso",
                "invite_id": invite_id,
                "invite_code": invite_code
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Erro ao criar convite por email: {str(e)}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            return jsonify({"error": f"Erro ao criar convite: {str(e)}"}), 500

    @staticmethod
    def generate_invite_link(inviter_id):
        """Gera um link de convite único"""
        try:
            invite_id, invite_code = InviteModel.create_invite_by_link(inviter_id)
            
            invite_link = f"{Config.FRONT_BASE_URL}/register?invite={invite_code}"
            
            return jsonify({
                "message": "Link de convite gerado com sucesso",
                "invite_id": invite_id,
                "invite_code": invite_code,
                "invite_link": invite_link
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Erro ao gerar link de convite: {str(e)}")
            import traceback
            current_app.logger.error(traceback.format_exc())
            return jsonify({"error": f"Erro ao gerar link: {str(e)}"}), 500

    @staticmethod
    def get_user_invites(user_id):
        """Retorna todos os convites feitos por um usuário"""
        try:
            invites = InviteModel.get_user_invites(user_id)
            return jsonify({"invites": invites}), 200
        except Exception as e:
            current_app.logger.error(f"Erro ao buscar convites: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @staticmethod
    def get_user_invited_friends(user_id):
        """Retorna a lista de amigos convidados de um usuário"""
        try:
            friends = InviteModel.get_user_invited_friends(user_id)
            return jsonify({"invited_friends": friends}), 200
        except Exception as e:
            current_app.logger.error(f"Erro ao buscar amigos convidados: {str(e)}")
            return jsonify({"error": str(e)}), 500

    @staticmethod
    def verify_invite_code(invite_code):
        """Verifica se um código de convite é válido"""
        try:
            invite = InviteModel.get_invite_by_code(invite_code)
            if invite:
                if invite['status'] == 'pending':
                    return jsonify({
                        "valid": True,
                        "invite": {
                            "invite_code": invite['invite_code'],
                            "invited_by_link": invite.get('invited_by_link', False),
                            "invited_email": invite.get('invited_email')
                        }
                    }), 200
                else:
                    return jsonify({
                        "valid": False,
                        "error": "Este convite já foi utilizado"
                    }), 400
            return jsonify({"valid": False, "error": "Código de convite inválido"}), 400
        except Exception as e:
            current_app.logger.error(f"Erro ao verificar código de convite: {str(e)}")
            return jsonify({"error": str(e)}), 500

