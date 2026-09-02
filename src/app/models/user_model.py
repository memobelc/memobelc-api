from src.app import mongo
import random
from bson import ObjectId
import string
from datetime import datetime

from src.app.models.push_notification_model import PushNotificationModel

ALLOWED_ROLES = ("user", "teacher", "admin")
ADDRESS_FIELDS = (
    "postal_code",
    "street",
    "number",
    "complement",
    "neighborhood",
    "city",
    "state",
)


class UserModel:
    def __init__(self, _id=None, name = None, email=None, password=None, collections=None, customer_id=None, asaas_customer_id=None, role='user', roles=None, **kwargs):
        self._id = str(_id) if _id else None
        self.name = name
        self.email = email
        self.password = password
        self.collections = collections or []
        self.customer_id = customer_id
        self.asaas_customer_id = asaas_customer_id
        self.cpf_cnpj = kwargs.get("cpf_cnpj")
        self.image = kwargs.get("image")
        self.address = kwargs.get("address") or {}
        self.coins = int(kwargs.get("coins") or 0)
        self.is_confirmed = kwargs.get("is_confirmed", False)
        self.must_change_password = bool(kwargs.get("must_change_password", False))
        self.roles = UserModel.normalize_roles(role=role, roles=roles)
        self.role = UserModel.primary_role(self.roles)

    @staticmethod
    def normalize_roles(role=None, roles=None):
        """Normaliza role string legado e/ou lista roles para um array válido e único."""
        result = []
        if roles:
            if isinstance(roles, str):
                result.append(roles)
            else:
                result.extend(list(roles))
        elif role:
            result.append(role)

        seen = []
        for item in result:
            if item in ALLOWED_ROLES and item not in seen:
                seen.append(item)
        return seen or ["user"]

    @staticmethod
    def primary_role(roles):
        """Role primária para compatibilidade com o campo legado `role`."""
        if "admin" in roles:
            return "admin"
        if "teacher" in roles:
            return "teacher"
        return "user"

    def has_role(self, role):
        return role in self.roles

    def get_roles(self):
        return list(self.roles)


    def save_to_db(self):
        """Salva o usuário no banco de dados MongoDB"""
        user_data = {
            'name': self.name,
            'email': self.email,
            'password': self.password,
            'is_confirmed': False,
            "collections": self.collections,
            "customer_id": self.customer_id,
            "asaas_customer_id": self.asaas_customer_id,
            "role": self.role,
            "roles": self.roles,
            "must_change_password": bool(self.must_change_password),
            "cpf_cnpj": self.cpf_cnpj,
            "image": self.image,
            "address": self.address or {},
            "coins": int(self.coins or 0),
        }
        result = mongo.db.users.insert_one(user_data)
        self._id = str(result.inserted_id)
        return True

    @staticmethod
    def set_asaas_customer_id(user_id, asaas_customer_id):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"asaas_customer_id": asaas_customer_id}},
        )

    @staticmethod
    def set_cpf_cnpj(user_id, cpf_cnpj):
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"cpf_cnpj": cpf_cnpj}},
        )

    @staticmethod
    def set_name(user_id, name):
        if not name:
            return
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"name": name}},
        )

    @staticmethod
    def normalize_address(data):
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("address must be an object")
        return {
            field: str(data.get(field) or "").strip()
            for field in ADDRESS_FIELDS
        }

    @staticmethod
    def update_profile(user_id, updates):
        if not updates:
            return UserModel.find_by_id(user_id)
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updates},
        )
        if result.matched_count == 0:
            return None
        return UserModel.find_by_id(user_id)

    @staticmethod
    def increment_coins(user_id, amount):
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"coins": int(amount)}},
        )
        if result.matched_count == 0:
            return None
        refreshed = mongo.db.users.find_one({"_id": ObjectId(user_id)}, {"coins": 1})
        return int((refreshed or {}).get("coins") or 0)

    @staticmethod
    def spend_coins(user_id, amount):
        amount = int(amount)
        if amount <= 0:
            return None
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id), "coins": {"$gte": amount}},
            {"$inc": {"coins": -amount}},
        )
        if result.matched_count == 0:
            return None
        refreshed = mongo.db.users.find_one({"_id": ObjectId(user_id)}, {"coins": 1})
        return int((refreshed or {}).get("coins") or 0)

    @staticmethod
    def get_document(user_id):
        return mongo.db.users.find_one({"_id": ObjectId(user_id)})

    @staticmethod
    def find_by_cpf_cnpj(cpf_cnpj):
        digits = "".join(ch for ch in str(cpf_cnpj or "") if ch.isdigit())
        if not digits:
            return None
        candidates = [digits]
        if len(digits) == 11:
            candidates.append(f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}")
        elif len(digits) == 14:
            candidates.append(f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}")
        user_data = mongo.db.users.find_one({"cpf_cnpj": {"$in": candidates}})
        if user_data:
            return UserModel(**user_data)
        return None

    @staticmethod
    def create_pending_user(name, email):
        """Cria usuário pendente para venda externa (sem senha definida)."""
        existing = UserModel.find_by_email(email)
        if existing:
            return existing
        from werkzeug.security import generate_password_hash
        import uuid
        user = UserModel(
            name=name or email.split("@")[0],
            email=email.lower(),
            password=generate_password_hash(uuid.uuid4().hex),
        )
        user.save_to_db()
        return UserModel.find_by_email(email)
    
    @staticmethod
    def add_collections_to_user(user_id, collection_ids):
        """Adiciona uma lista de collection IDs ao user especificado"""
        
        collection_object_ids = [ObjectId(collection_id) for collection_id in collection_ids]
        
        
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$addToSet": {"collections": {"$each": collection_object_ids}}}
        )
        
        return result.modified_count > 0

    @staticmethod
    def find_by_email(email):
        """Busca um usuário pelo email"""
        if not email:
            return None
        email_lower = str(email).strip().lower()
        user_data = mongo.db.users.find_one({'email': email_lower})
        if not user_data:
            user_data = mongo.db.users.find_one({'email': email})
        if user_data:
            return UserModel(**user_data)
        return None

    @staticmethod
    def find_by_id(user_id):
        """Busca um usuário pelo ID"""
        user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return UserModel(**user_data)
        return None
    
    @staticmethod
    def verify_is_confirmed(email):
        """Verificar se um usuário está confirmado!"""
        user_data = mongo.db.users.find_one({'email': email})
        if user_data and user_data['is_confirmed']:
            return True
        else:
            return False
        
        
    @staticmethod
    def verify_code(email, code):
        user_data = mongo.db.users.find_one({'email': email})
        
        if not UserModel.verify_is_confirmed(email) and user_data['code'] == code:
            return True
        else:
            return False
        

    
    @staticmethod
    def turn_confirmed(email):
        """Alterar o status de um usuário para confirmado"""
        mongo.db.users.update_one({'email': email}, {'$set': {'is_confirmed': True}})
        mongo.db.users.update_one({'email': email}, {'$unset': {'code':''}})
        
    @staticmethod
    def generate_code(email):
        code = ''.join(random.choices(string.digits, k=6))
        mongo.db.users.update_one({'email': email}, {'$set': {'code':code}})
        return code
    
    @staticmethod
    def generate_reset_code(email):
        """Gera um código de 6 dígitos para recuperação de senha e salva com expiração de 15 minutos."""
        from datetime import timedelta, timezone
        code = ''.join(random.choices(string.digits, k=6))
        expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
        mongo.db.users.update_one(
            {'email': email}, 
            {'$set': {
                'reset_code': code,
                'reset_code_expiry': expiry
            }}
        )
        return code
    
    @staticmethod
    def get_reset_code_data(email):
        """Retorna os dados do código de reset (código e expiração) para um email."""
        user_data = mongo.db.users.find_one({'email': email.lower()})
        if not user_data:
            return None
        
        return {
            'reset_code': user_data.get('reset_code'),
            'reset_code_expiry': user_data.get('reset_code_expiry')
        }
    
    @staticmethod
    def remove_reset_code(email):
        """Remove o código de reset e sua expiração após uso bem-sucedido."""
        result = mongo.db.users.update_one(
            {'email': email.lower()},
            {'$unset': {'reset_code': '', 'reset_code_expiry': ''}}
        )
        return result.modified_count > 0
        
        
    @staticmethod
    def update_password(user_id,  new_password):
        user = UserModel.find_by_id(user_id)
        
        if user:
            
            mongo.db.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {'password': new_password, 'must_change_password': False}}
            )
            return True
        
        return False
    
    @staticmethod
    def verify_user_is_guest(user_id):
        user = UserModel.find_by_id(user_id)
        
        if not user or not hasattr(user, 'email'):
            return [] 

        result = mongo.db.classrooms.find({'guests': user.email})

        list_classrooms = []
        
        for classroom in result:
            list_classrooms.append({'_id': str(classroom.get('_id'))})
        
        return list_classrooms
    
    @staticmethod
    def mail_list(name, email):
        user_data = {
            'name': name,
            'email': email,
        }
        
        
        mongo.db.list_emails.insert_one(user_data)
        return True

    
    
    @staticmethod
    def save_user_access_log(data):
        # user_id é obrigatório, os demais campos podem ser None
        user_id = data.get("user_id")
        if not user_id:
            return False
        
        user_acess_log = {
            'user_id': ObjectId(user_id),
            "deviceName": data.get("deviceName"),
            "deviceType": data.get("deviceType"),
            "expoPushToken": data.get("expoPushToken"),
            "isPhysicalDevice": data.get("isPhysicalDevice"),
            "manufacturer": data.get("manufacturer"),
            "osName": data.get("osName"),
            "osVersion": data.get("osVersion"),
            "platformApiLevel": data.get("platformApiLevel"),
            "created_at": datetime.utcnow()
        
        }
        mongo.db.user_access_log.insert_one(user_acess_log)

        # também salva/atualiza o token de push para o usuário
        expo_token = data.get("expoPushToken")
        if expo_token:
            PushNotificationModel.save_token(
                user_id=str(user_id),
                push_token=expo_token,
                device_info={
                    "deviceName": data.get("deviceName"),
                    "deviceType": data.get("deviceType"),
                    "osName": data.get("osName"),
                    "osVersion": data.get("osVersion"),
                    "platformApiLevel": data.get("platformApiLevel"),
                    "isPhysicalDevice": data.get("isPhysicalDevice"),
                    "manufacturer": data.get("manufacturer"),
                },
            )
        return True



    @staticmethod
    def list_users(search=None):
        """Lista usuários para gestão admin (id, nome, email, roles)."""
        query = {}
        if search:
            query = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                ]
            }
        cursor = mongo.db.users.find(
            query,
            {"name": 1, "email": 1, "role": 1, "roles": 1, "coins": 1, "image": 1},
        )
        users = []
        for user_data in cursor:
            roles = UserModel.normalize_roles(
                role=user_data.get("role"),
                roles=user_data.get("roles"),
            )
            users.append({
                "_id": str(user_data["_id"]),
                "name": user_data.get("name"),
                "email": user_data.get("email"),
                "role": UserModel.primary_role(roles),
                "roles": roles,
                "coins": int(user_data.get("coins") or 0),
                "image": user_data.get("image"),
            })
        return users

    @staticmethod
    def update_roles(user_id, roles):
        """Atualiza as roles de um usuário. Retorna o usuário atualizado ou None."""
        normalized = UserModel.normalize_roles(roles=roles)
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"roles": normalized, "role": UserModel.primary_role(normalized)}},
        )
        if result.matched_count == 0:
            return None
        return UserModel.find_by_id(user_id)

    def to_dict(self):
        """Converte o objeto UserModel para dicionário"""
        return {
            '_id': self._id,
            'name': self.name,
            'email': self.email,
            'collections': [str(ObjectId(collection_id)) for collection_id in self.collections],
            'customer_id': self.customer_id,
            'asaas_customer_id': self.asaas_customer_id,
            'role': self.role,
            'roles': self.roles,
        }
