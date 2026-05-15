from aiogram.fsm.state import StatesGroup, State

class AddShiftTaskForm(StatesGroup):
    title = State()
    description = State()
    weekday = State()

class EditShiftTaskForm(StatesGroup):
    title = State()
    description = State()
    weekday = State()
    
class TestCreationForm(StatesGroup):
    name = State()
    description = State()

class ResetProgressForm(StatesGroup):
    telegram_id = State()

class QuestionStreamForm(StatesGroup):
    question_text = State()
    images = State()  # Состояние для загрузки одного или нескольких изображений
    option_a = State()
    option_b = State()
    option_c = State()
    option_d = State()
    correct_answer = State()

class AddQuestionForm(StatesGroup):
    select_test = State()
    question_text = State()
    option_a = State()
    option_b = State()
    option_c = State()
    option_d = State()
    correct_answer = State()

class EditQuestionForm(StatesGroup):
    select_test_for_edit = State()
    select_question_to_edit = State()
    question_text = State()
    option_a = State()
    option_b = State()
    option_c = State()
    option_d = State()
    correct_answer = State()

class DeleteQuestionForm(StatesGroup):
    select_test_for_delete = State()
    question_id = State()

class AddMaterialsForm(StatesGroup):
    name = State()
    file = State()
class AddExamForm(StatesGroup):
    name = State()
    file = State()

class BulkAddQuestionsForm(StatesGroup):
    text = State()

