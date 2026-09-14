from src.app.models.classroom_model import ClassroomModel
from src.app.models.collection_model import CollectionModel
from src.app.models.user_model import UserModel
from src.app.services.notification_service import NotificationService

class ClassroomService:
    
    @staticmethod
    def createClassroom(collection_id, user_id):
        collection = CollectionModel.get_by_id(collection_id)
        classrooms = ClassroomModel(name=collection.get('name'), teacher=user_id, collection=collection_id)
        result = classrooms.save_to_db()
        
        CollectionModel.add_classroom(result.get('class_id'), classrooms.collection)
        return result
    
    @staticmethod
    def getClassrooms(user_id):
        teacher_classrooms = ClassroomModel.get_classrooms_by_user(user_id)
        for c in teacher_classrooms:
            c['user_role'] = 'teacher'

        student_classrooms = ClassroomModel.get_classrooms_as_student(user_id)
        teacher_ids = {c['_id'] for c in teacher_classrooms}
        for c in student_classrooms:
            c['user_role'] = 'student'

        # Exclude duplicates (edge case where teacher is also in students array)
        student_classrooms = [c for c in student_classrooms if c['_id'] not in teacher_ids]

        return {'classrooms': teacher_classrooms + student_classrooms}

    @staticmethod
    def get_public_classroom(classroom_id):
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return None
        if not classroom.get('checkout_allowed') or not classroom.get('checkout_enabled'):
            return None
        price = classroom.get('price')
        return {
            '_id': classroom['_id'],
            'name': classroom.get('name'),
            'image': classroom.get('image'),
            'price': float(price) if price is not None else None,
            'checkout_enabled': True,
            'checkout_allowed': True,
            'checkout_url': classroom.get('checkout_url'),
        }

    @staticmethod
    def update_classroom(user, classroom_id, data):
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return {'error': 'Classroom not found'}, 404

        is_admin = user.has_role('admin')
        is_owner = str(classroom.get('teacher')) == str(user._id)
        if not is_admin and not is_owner:
            return {'error': 'Unauthorized'}, 403

        update_data = {}
        if is_admin and 'checkout_allowed' in data:
            update_data['checkout_allowed'] = bool(data.get('checkout_allowed'))
            if not update_data['checkout_allowed']:
                update_data['checkout_enabled'] = False

        allowed_now = classroom.get('checkout_allowed')
        if 'checkout_allowed' in update_data:
            allowed_now = update_data['checkout_allowed']

        teacher_keys = is_owner or is_admin
        if teacher_keys:
            if 'checkout_enabled' in data and 'checkout_enabled' not in update_data:
                if data.get('checkout_enabled') and not allowed_now:
                    return {'error': 'Checkout is not allowed for this classroom'}, 403
                update_data['checkout_enabled'] = bool(data.get('checkout_enabled'))
            if 'price' in data:
                raw_price = data.get('price')
                if raw_price is None or raw_price == '':
                    update_data['price'] = None
                else:
                    try:
                        price = float(raw_price)
                    except (TypeError, ValueError):
                        return {'error': 'Invalid price'}, 400
                    if price < 0:
                        return {'error': 'Invalid price'}, 400
                    update_data['price'] = price
            if 'name' in data and data.get('name'):
                update_data['name'] = data.get('name')
            if 'image' in data:
                raw_image = data.get('image')
                update_data['image'] = raw_image if raw_image else None

        if not update_data:
            return classroom, 200
        updated = ClassroomModel.update(classroom_id, update_data)
        return updated, 200
    
    @staticmethod
    def get_student_classroom_profile(classroom_id, student_id):
        from src.app import mongo
        from bson import ObjectId as ObjId

        user = mongo.db.users.find_one(
            {'_id': ObjId(student_id)},
            {'_id': 1, 'name': 1, 'email': 1, 'created_at': 1}
        )
        if not user:
            return None

        access_logs = list(
            mongo.db.user_access_log
            .find({'user_id': ObjId(student_id)}, {'_id': 0, 'created_at': 1})
            .sort('created_at', -1)
        )

        last_access = None
        if access_logs and access_logs[0].get('created_at'):
            ts = access_logs[0]['created_at']
            last_access = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)

        active_days = set()
        for log in access_logs:
            ts = log.get('created_at')
            if ts and hasattr(ts, 'date'):
                active_days.add(ts.date())

        courses_raw = list(
            mongo.db.courses
            .find({'classroom_id': ObjId(classroom_id)})
            .sort('created_at', 1)
        )

        total_lessons_all = 0
        total_lessons_viewed = 0
        total_activities_all = 0
        total_activities_submitted = 0
        all_scores = []
        total_xp = 0
        has_perfect = False
        courses_data = []

        for course in courses_raw:
            course_id_obj = course['_id']
            course_id = str(course_id_obj)

            modules = list(
                mongo.db.course_modules
                .find({'course_id': course_id_obj})
                .sort('order', 1)
            )

            course_lessons_viewed = 0
            course_lessons_total = 0
            course_activities_submitted = 0
            course_activities_total = 0
            course_scores = []
            course_xp = 0
            modules_data = []

            for module in modules:
                module_id_obj = module['_id']
                lessons = list(
                    mongo.db.lessons.find({'module_id': module_id_obj}).sort('order', 1)
                )
                activities = list(
                    mongo.db.activities.find({'module_id': module_id_obj}).sort('order', 1)
                )

                lessons_data = []
                for lesson in lessons:
                    viewed_doc = mongo.db.lesson_views.find_one({
                        'lesson_id': lesson['_id'],
                        'student_id': ObjId(student_id),
                    })
                    course_lessons_total += 1
                    if viewed_doc:
                        course_lessons_viewed += 1
                    viewed_at = None
                    if viewed_doc and viewed_doc.get('viewed_at'):
                        ts = viewed_doc['viewed_at']
                        viewed_at = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
                    lessons_data.append({
                        '_id': str(lesson['_id']),
                        'title': lesson.get('title', ''),
                        'viewed': viewed_doc is not None,
                        'viewed_at': viewed_at,
                    })

                activities_data = []
                for activity in activities:
                    answer_doc = mongo.db.student_answers.find_one({
                        'activity_id': activity['_id'],
                        'student_id': ObjId(student_id),
                    })
                    course_activities_total += 1
                    if answer_doc:
                        course_activities_submitted += 1
                        mode = activity.get('feedback_mode') or 'immediate'
                        released = mode == 'immediate' or answer_doc.get('approved')
                        if released and answer_doc.get('score') is not None:
                            course_scores.append(answer_doc['score'])
                            if answer_doc['score'] >= 100:
                                has_perfect = True
                        if released:
                            course_xp += answer_doc.get('earned_points') or 0
                    submitted_at = None
                    if answer_doc and answer_doc.get('submitted_at'):
                        ts = answer_doc['submitted_at']
                        submitted_at = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
                    mode = activity.get('feedback_mode') or 'immediate'
                    released = bool(
                        answer_doc and (
                            mode == 'immediate' or answer_doc.get('approved')
                        )
                    )
                    activities_data.append({
                        '_id': str(activity['_id']),
                        'title': activity.get('title', ''),
                        'submitted': answer_doc is not None,
                        'score': answer_doc.get('score') if released else None,
                        'submitted_at': submitted_at,
                        'approved': answer_doc.get('approved', False) if answer_doc else False,
                    })

                modules_data.append({
                    '_id': str(module_id_obj),
                    'name': module.get('name', ''),
                    'lessons': lessons_data,
                    'activities': activities_data,
                })

            total_lessons_all += course_lessons_total
            total_lessons_viewed += course_lessons_viewed
            total_activities_all += course_activities_total
            total_activities_submitted += course_activities_submitted
            all_scores.extend(course_scores)

            total_xp += course_xp

            avg_score = round(sum(course_scores) / len(course_scores), 1) if course_scores else None
            total_items = course_lessons_total + course_activities_total
            done_items = course_lessons_viewed + course_activities_submitted
            progress_pct = round(done_items / max(total_items, 1) * 100, 1)

            courses_data.append({
                '_id': course_id,
                'name': course.get('name', ''),
                'description': course.get('description', ''),
                'lessons_viewed': course_lessons_viewed,
                'total_lessons': course_lessons_total,
                'activities_submitted': course_activities_submitted,
                'total_activities': course_activities_total,
                'avg_score': avg_score,
                'xp': int(round(course_xp)),
                'progress_pct': progress_pct,
                'modules': modules_data,
            })

        progress_docs = list(mongo.db.user_progress.find({'user_id': ObjId(student_id)}))
        total_cards = len(progress_docs)
        cards_reviewed = sum(1 for p in progress_docs if p.get('attempts', 0) > 0)

        overall_avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else None
        lessons_pct = round(total_lessons_viewed / max(total_lessons_all, 1) * 100, 1)
        activities_pct = round(total_activities_submitted / max(total_activities_all, 1) * 100, 1)

        at_risk = (overall_avg_score is not None and overall_avg_score < 60) or (
            total_lessons_all > 0 and lessons_pct < 40
        )
        top_performer = (overall_avg_score is not None and overall_avg_score >= 85) and (
            total_lessons_all == 0 or lessons_pct >= 80
        )

        member_since = None
        if user.get('created_at'):
            ts = user['created_at']
            member_since = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)

        badges = []
        if total_activities_submitted >= 1:
            badges.append('first_step')
        if has_perfect:
            badges.append('perfect')
        if top_performer:
            badges.append('top_performer')
        if at_risk:
            badges.append('at_risk')

        return {
            'student': {
                '_id': str(user['_id']),
                'name': user.get('name', ''),
                'email': user.get('email', ''),
                'member_since': member_since,
            },
            'access': {
                'last_access': last_access,
                'total_logins': len(access_logs),
                'active_days': len(active_days),
            },
            'summary': {
                'total_lessons': total_lessons_all,
                'lessons_viewed': total_lessons_viewed,
                'lessons_pct': lessons_pct,
                'total_activities': total_activities_all,
                'activities_submitted': total_activities_submitted,
                'activities_pct': activities_pct,
                'overall_avg_score': overall_avg_score,
                'total_cards': total_cards,
                'cards_reviewed': cards_reviewed,
                'at_risk': at_risk,
                'top_performer': top_performer,
                'xp': int(round(total_xp)),
                'badges': badges,
            },
            'courses': courses_data,
        }

    @staticmethod
    def add_students(classroom_id, email_user):
        user = UserModel.find_by_email(email_user)
        
        if user:
            ClassroomModel.add_students(classroom_id, user._id)
            # notifica o usuário que foi adicionado à classroom
            NotificationService.notify_user_added_to_classroom(
                classroom_id=classroom_id, user_id=str(user._id)
            )
            
        else:
            ClassroomModel.add_guest(classroom_id, email_user)
        
        return {}

    @staticmethod
    def remove_user(classroom_id, user_id=None, email=None):
        if user_id:
            ClassroomModel.remove_student(classroom_id, user_id)
            user = UserModel.find_by_id(user_id)
            if user and getattr(user, "email", None):
                ClassroomModel.remove_user_guest(classroom_id, user.email)
        if email:
            ClassroomModel.remove_user_guest(classroom_id, email)
        return {}

        
