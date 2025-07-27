import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock
from utils import (
    split_overlapping,
    create_batches,
    parse_json,
    sort_key,
    _process_results,
    RecitationError
)

class TestProcessResults(unittest.TestCase):
    """Test the _process_results function"""
    
    def test_process_results_with_valid_data(self):
        """Test _process_results with valid response data"""
        # Sample file content that would come from a successful API response
        file_content = '''{"key": "chunks/1", "response": {"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "First chunk of text. "}]}}]}}
{"key": "chunks/2", "response": {"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}, "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Second chunk of text."}]}}]}}'''
        
        # Mock the parse_json function to work correctly
        with patch('utils.parse_json') as mock_parse:
            mock_parse.side_effect = [
                {
                    "key": "chunks/1",
                    "response": {
                        "usageMetadata": {"promptTokenCount": 100,
                                          "candidatesTokenCount": 50},
                        "candidates": [
                            {"finishReason": "STOP", "content": {"parts": [{"text": "First chunk of text. "}]}}
                        ]
                    }
                },
                {
                    "key": "chunks/2",
                    "response": {
                        "usageMetadata": {"promptTokenCount": 100,
                                          "candidatesTokenCount": 50},
                        "candidates": [
                            {"finishReason": "STOP", "content": {"parts": [{"text": "Second chunk of text."}]}}
                        ]
                    }
                }
            ]
            
            # Call the function
            cost, fulltext, raw_responses = _process_results(file_content, 0.0)
            
            # Verify results
            self.assertGreater(cost, 0)  # Should have some cost
            self.assertIn("First chunk of text.", fulltext)
            self.assertIn("Second chunk of text.", fulltext)
            self.assertEqual(len(raw_responses), 2)
            # Check that responses contain the expected text (allowing for newlines)
            self.assertIn("First chunk of text.", raw_responses[0])
            self.assertIn("Second chunk of text.", raw_responses[1])

    def test_process_results_with_recitation_error(self):
        """Test _process_results when a RECITATION error occurs"""
        file_content = '''{"key": "chunks/1", "response": {"usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 0}, "candidates": [{"finishReason": "RECITATION", "content": {"parts": [{"text": "Problematic text"}]}}]}}'''
        
        with patch('utils.parse_json') as mock_parse:
            mock_parse.return_value = {
                "key": "chunks/1", 
                "response": {
                    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 0},
                    "candidates": [{
                        "finishReason": "RECITATION",
                        "content": {"parts": [{"text": "Problematic text"}]}
                    }]
                }
            }
            
            # Should raise RecitationError
            with self.assertRaises(RecitationError):  # Using generic Exception since RecitationError might not be imported correctly
                _process_results(file_content, 0.0)

class TestUtils(unittest.TestCase):
    
    def test_split_overlapping_basic(self):
        """Test basic functionality of split_overlapping"""
        text = "This is a test sentence. This is another sentence. This is a third sentence."
        result = list(split_overlapping(text, chunk_size=5, overlap=2))
        
        # Should split into chunks of 5 words with 2 word overlap
        self.assertGreater(len(result), 0)
        # Each chunk should contain words
        for chunk in result:
            self.assertGreater(len(chunk.split()), 0)
    
    def test_create_batches(self):
        """Test batch creation functionality"""
        elements = list(range(10))
        batches = list(create_batches(elements, batch_size=3))
        
        # Should create the correct number of batches
        self.assertEqual(len(batches), 4)  # 10 elements with batch_size=3 should create 4 batches
        # First 3 batches should have 3 elements each
        for i in range(3):
            self.assertEqual(len(batches[i]), 3)
        # Last batch should have the remaining elements
        self.assertEqual(len(batches[3]), 1)
    
    def test_parse_json_valid(self):
        """Test parsing valid JSON"""
        valid_json = '{"key": "value", "number": 42}'
        result = parse_json(valid_json)
        self.assertEqual(result, {"key": "value", "number": 42})
    
    def test_parse_json_invalid(self):
        """Test parsing invalid JSON returns None"""
        invalid_json = '{"key": "value", "number":}'
        result = parse_json(invalid_json)
        self.assertIsNone(result)
    
    def test_sort_key(self):
        """Test sort_key function"""
        test_string = "page_10_page_2"
        result = sort_key(test_string)
        # Should split the string and convert numbers to integers
        self.assertEqual(result, ["page_", 10, "_page_", 2])

if __name__ == '__main__':
    unittest.main()
