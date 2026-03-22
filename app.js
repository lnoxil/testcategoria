const state = {
  allQuestions: [],
  testQuestions: [],
  index: 0,
  correct: 0,
};

const categorySelect = document.getElementById('categorySelect');
const countInput = document.getElementById('countInput');
const startBtn = document.getElementById('startBtn');
const quiz = document.getElementById('quiz');
const questionText = document.getElementById('questionText');
const optionsForm = document.getElementById('optionsForm');
const progress = document.getElementById('progress');
const nextBtn = document.getElementById('nextBtn');
const result = document.getElementById('result');

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function renderQuestion() {
  const q = state.testQuestions[state.index];
  progress.textContent = `Вопрос ${state.index + 1} из ${state.testQuestions.length}`;
  questionText.textContent = `${q.question_number}. ${q.question}`;
  optionsForm.innerHTML = q.options
    .map((opt, i) => `<label class="option"><input type="radio" name="answer" value="${i}" /> ${opt}</label>`)
    .join('');
}

function finish() {
  quiz.classList.add('hidden');
  result.classList.remove('hidden');
  const total = state.testQuestions.length;
  const pct = Math.round((state.correct / total) * 100);
  result.innerHTML = `<h2>Результат</h2><p class="${pct >= 80 ? 'good' : 'bad'}">${state.correct} из ${total} (${pct}%)</p>`;
}

startBtn.addEventListener('click', () => {
  const category = Number(categorySelect.value);
  const max = Number(countInput.value || 20);
  const pool = state.allQuestions.filter((q) => q.category === category);
  state.testQuestions = shuffle(pool).slice(0, Math.min(max, pool.length));
  state.index = 0;
  state.correct = 0;
  result.classList.add('hidden');
  quiz.classList.remove('hidden');
  renderQuestion();
});

nextBtn.addEventListener('click', () => {
  const checked = optionsForm.querySelector('input[name="answer"]:checked');
  if (!checked) {
    alert('Выберите ответ');
    return;
  }
  const value = Number(checked.value);
  const q = state.testQuestions[state.index];
  if (value === q.correct_option_index) state.correct += 1;
  state.index += 1;
  if (state.index >= state.testQuestions.length) {
    finish();
    return;
  }
  renderQuestion();
});

async function init() {
  const data = await fetch('./data/questions.json').then((r) => r.json());
  state.allQuestions = data;
  const categories = [...new Set(data.map((q) => q.category))].sort((a, b) => a - b);
  categorySelect.innerHTML = categories.map((c) => `<option value="${c}">Категория ${c}</option>`).join('');
  countInput.max = data.length;
}

init();
