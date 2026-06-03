import unittest
from unittest.mock import Mock, patch

from app.features.blogs.services.generation.openai import generate_blog


class BlogGenerationRegressionTests(unittest.TestCase):
    def test_generate_blog_keeps_default_max_output_tokens(self):
        response = Mock()
        response.output_text = "# Blog\n\nInhoud"

        with patch(
            "app.features.blogs.services.generation.openai.create_response",
            return_value=response,
        ) as create_response:
            result = generate_blog("Schrijf een blog", user_id="user-1")

        self.assertEqual(result, "# Blog\n\nInhoud")
        self.assertEqual(create_response.call_args.kwargs["max_output_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()
