# states/forms.py
from aiogram.fsm.state import StatesGroup, State

class TestCreationForm(StatesGroup):
    name = State()
    description = State()

class AddQuestionForm(StatesGroup):
    select_test = State()
    question_text = State()
    option_a = State()
    option_b = State()
    option_c = State()
    option_d = State()
    correct_answer = State()

class EditQuestionForm(StatesGroup):
    select_test = State()
    question_id = State()
    question_text = State()
    option_a = State()
    option_b = State()
    option_c = State()
    option_d = State()
    correct_answer = State()
