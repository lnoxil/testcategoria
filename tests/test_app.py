import unittest

import app


class QuizAppTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True)
        self.client = app.app.test_client()

    def test_home_page(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        page = res.get_data(as_text=True)
        self.assertIn('Начать общий тест списком (50 вопросов)', page)
        self.assertIn('Быстрый тест (20 вопросов)', page)

    def test_common_test_starts_with_50_questions(self):
        self.client.post('/start', data={'mode': 'common_50'})
        with self.client.session_transaction() as sess:
            self.assertEqual(len(sess['test_ids']), 50)
            self.assertEqual(sess['index'], 0)

    def test_quick_test_starts_with_20_questions(self):
        self.client.post('/start', data={'mode': 'quick_20'})
        with self.client.session_transaction() as sess:
            self.assertEqual(len(sess['test_ids']), 20)

    def test_start_redirects_to_list_mode(self):
        res = self.client.post('/start', data={'mode': 'common_50'}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/list_test', res.headers.get('Location', ''))

    def test_exit_test_clears_test_state(self):
        self.client.post('/start', data={'mode': 'common_50'})
        self.client.get('/exit_test')
        with self.client.session_transaction() as sess:
            self.assertNotIn('test_ids', sess)

    def test_editor_page_loads(self):
        res = self.client.get('/editor')
        self.assertEqual(res.status_code, 200)
        page = res.get_data(as_text=True)
        self.assertIn('Редактор тестов', page)

    def test_parse_questions_from_text(self):
        raw = (
            "Вопрос 1\n"
            "Тестовый вопрос?\n"
            "Выберите один ответ:\n"
            "a. вариант 1\n"
            "b. вариант 2\n"
            "Правильный ответ: вариант 2\n"
        )
        parsed = app.parse_questions_from_text(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question_number"], 1)
        self.assertEqual(parsed[0]["correct_option_index"], 1)


if __name__ == '__main__':
    unittest.main()
