import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock
from harmonization import (
    normalize,
    apply_table_of_contents
)

class TestApplyTableOfContents(unittest.TestCase):
    """Test the apply_table_of_contents function"""
    
    def setUp(self):
        """Set up test data"""
        self.sample_headings = [
            {"text": "Introduction", "level": "1"},
            {"text": "Chapter One: The Beginning", "level": "1"},
            {"text": "Section 1.1: First Topic", "level": "2"}
        ]
        
        self.sample_text = """This is introductory text that comes before any headings.

This is the introduction to the document.

Chapter One: The Beginning

This is the content of the first chapter. It talks about important things.

Section 1.1: First Topic

This section covers the first topic in detail."""



    def test_normalize(self):
        """Test normalize function"""
        test_string = "  This,  is # a   test string  "
        result = normalize(test_string)
        # Should remove extra spaces and replace commas and hashes with spaces
        self.assertEqual(result, "this is a test string")
    
    def test_normalize_remove_whitespace(self):
        """Test normalize function with remove_whitespace flag"""
        test_string = "  This,  is # a   test string  "
        result = normalize(test_string, remove_whitespace=True)
        # Should remove all spaces
        self.assertEqual(result, "thisisateststring")
        
    def test_apply_table_of_contents_basic(self):
        """Test basic application of table of contents to text"""
        result = apply_table_of_contents(self.sample_text, self.sample_headings)
        
        # Check that the result is a string
        self.assertIsInstance(result, str)
        
        # Check that headings are added (they should appear as markdown headings)
        self.assertNotIn("# Introduction", result)
        self.assertIn("# Chapter One: The Beginning", result)
        self.assertIn("## Section 1.1: First Topic", result)

    def test_apply_table_of_contents_empty_text(self):
        """Test applying table of contents to empty text"""
        result = apply_table_of_contents("", self.sample_headings)
        self.assertEqual(result, "")

    def test_apply_table_of_contents_no_headings(self):
        """Test applying empty headings to text"""
        result = apply_table_of_contents(self.sample_text, [])
        # Should return text unchanged
        self.assertEqual(result.strip(), self.sample_text.strip())

    def test_apply_table_of_contents_special_characters(self):
        """Test applying table of contents with special characters"""
        headings = [{"text": "Chapter 1: It's Important!", "level": "1"}]
        text = "This is some text.\n\nChapter 1: It's Important!\n\nMore text here."
        
        result = apply_table_of_contents(text, headings)
        self.assertIsInstance(result, str)
        
        # Check that the heading is properly formatted as a markdown heading
        self.assertIn("# Chapter 1: It's Important!", result)
        
        # Check that the original text is preserved
        self.assertIn("This is some text.", result)
        self.assertIn("More text here.", result)
        
        # Check that the original heading text is replaced with the markdown version
        # The function should add the markdown heading after the existing text
        lines = result.split('\n')
        heading_line_index = None
        for i, line in enumerate(lines):
            if "Chapter 1: It's Important!" in line and line.startswith('#'):
                heading_line_index = i
                break
        
        self.assertIsNotNone(heading_line_index, "Markdown heading not found in output")
