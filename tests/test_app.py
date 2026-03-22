import unittest

import app


class QuizAppTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True)
        self.client = app.app.test_client()

    def test_home_page(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Начать общий тест списком (50 вопросов)', res.get_data(as_text=True))

    def test_common_test_starts_with_50_questions(self):
        self.client.post('/start', data={'mode': 'common'})
        with self.client.session_transaction() as sess:
            self.assertEqual(len(sess['test_ids']), 50)
            self.assertEqual(sess['index'], 0)


    def test_start_redirects_to_list_mode(self):
        res = self.client.post('/start', data={'mode': 'common'}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/list_test', res.headers.get('Location', ''))

    def test_mistake_saved_after_wrong_answer(self):
        self.client.post('/start', data={'mode': 'common'})
        with self.client.session_transaction() as sess:
            qid = sess['test_ids'][0]
            q = app.QUESTIONS_BY_ID[qid]
            wrong = (q['correct_option_index'] + 1) % len(q['options'])

        self.client.post('/answer', data={'answer': str(wrong)})
        with self.client.session_transaction() as sess:
            self.assertIn(qid, sess.get('mistakes', []))


if __name__ == '__main__':
    unittest.main()
