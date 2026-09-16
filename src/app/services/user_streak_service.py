"""Service for handling user streak operations."""

from src.app.models.user_streak_model import UserStreakModel


class UserStreakService:
    """Service for managing user study streaks."""

    @staticmethod
    def record_study(user_id: str):
        """Registra que o usuário estudou hoje."""
        UserStreakModel.record_study_day(user_id)
        from src.app.models.mission_model import MissionModel
        MissionModel.complete_eligible_streak_missions(user_id)

    @staticmethod
    def get_streak(user_id: str):
        """Retorna informações do streak do usuário."""
        return UserStreakModel.get_streak_info(user_id)

