"""
HTML Cleaning Utility for ScamShield
====================================
Converts HTML job descriptions into readable plain text while preserving:
- Paragraphs
- Bullet points
- Numbered lists
- Line breaks
- Basic formatting

Used by scraper and ML pipeline to ensure clean text for analysis.
"""
import re
from html.parser import HTMLParser
from typing import Optional


class HTMLToTextParser(HTMLParser):
    """Parse HTML and convert to readable plain text."""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.in_script = False
        self.in_style = False
        self.line_buffer = []
        self.preserve_newlines = False
        
    def handle_starttag(self, tag, attrs):
        """Handle opening HTML tags."""
        tag = tag.lower()
        
        if tag in ('script', 'style'):
            self.in_script = (tag == 'script')
            self.in_style = (tag == 'style')
        elif tag in ('p', 'div', 'section', 'article'):
            self._flush_line()
        elif tag in ('br', ):
            self._flush_line()
        elif tag in ('li', 'dt', 'dd'):
            self._flush_line()
            if tag == 'li':
                self.line_buffer.append('• ')
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._flush_line()
        elif tag in ('ul', 'ol'):
            self._flush_line()
        elif tag in ('tr',):
            self._flush_line()
        elif tag in ('td', 'th'):
            pass  # don't add newlines, let space be added in between
            
    def handle_endtag(self, tag):
        """Handle closing HTML tags."""
        tag = tag.lower()
        
        if tag in ('script', 'style'):
            self.in_script = False
            self.in_style = False
        elif tag in ('p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._flush_line()
        elif tag in ('li', 'dt', 'dd'):
            self._flush_line()
        elif tag in ('ul', 'ol'):
            self._flush_line()
        elif tag in ('tr',):
            self._flush_line()
            
    def handle_data(self, data):
        """Handle text content."""
        if self.in_script or self.in_style:
            return
            
        # Clean up whitespace
        text = data.strip()
        if text:
            self.line_buffer.append(text)
            
    def handle_entityref(self, name):
        """Handle HTML entities like &nbsp; &amp; etc."""
        entities = {
            'nbsp': ' ',
            'amp': '&',
            'lt': '<',
            'gt': '>',
            'quot': '"',
            'apos': "'",
        }
        self.line_buffer.append(entities.get(name, f'&{name};'))
        
    def handle_charref(self, name):
        """Handle numeric character references like &#160;"""
        if name.startswith('x'):
            char = chr(int(name[1:], 16))
        else:
            char = chr(int(name))
        if char.isspace():
            self.line_buffer.append(' ')
        elif not char.iscntrl():
            self.line_buffer.append(char)
            
    def _flush_line(self):
        """Flush current line buffer and add to text."""
        line = ' '.join(self.line_buffer).strip()
        if line:
            self.text_parts.append(line)
        self.line_buffer = []
        
    def get_text(self) -> str:
        """Get the final cleaned text."""
        self._flush_line()
        # Join paragraphs and clean up multiple newlines
        text = '\n'.join(self.text_parts)
        # Replace multiple newlines with double newline (paragraph break)
        text = re.sub(r'\n\n+', '\n\n', text)
        # Replace multiple spaces with single space
        text = re.sub(r'  +', ' ', text)
        return text.strip()


def clean_html_description(html_text: Optional[str]) -> str:
    """
    Clean HTML-formatted job description to readable plain text.
    Preserves formatting, paragraphs, bullet points, and numbered lists.
    
    Args:
        html_text: Raw HTML text from scraper or form
        
    Returns:
        Clean plain text with formatting preserved
    """
    if not html_text:
        return ""
        
    # Handle bytes
    if isinstance(html_text, bytes):
        html_text = html_text.decode('utf-8', errors='ignore')
        
    # Convert to string
    html_text = str(html_text).strip()
    if not html_text:
        return ""
    
    # Quick check - if no HTML tags, return as-is
    if '<' not in html_text:
        return html_text
    
    try:
        parser = HTMLToTextParser()
        parser.feed(html_text)
        return parser.get_text()
    except Exception as e:
        # Fallback: use regex-based cleaning
        print(f"[warn] HTMLParser error: {e}, using regex fallback")
        return _clean_html_regex(html_text)


def _clean_html_regex(html_text: str) -> str:
    """Fallback HTML cleaning using regex."""
    # Remove script and style
    html_text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    
    # Replace <br> and <hr> with newlines
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'<hr\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    
    # Replace block elements with newlines
    html_text = re.sub(r'</?(p|div|section|article|h[1-6]|ul|ol|li|tr|td|th)>', '\n', html_text, flags=re.IGNORECASE)
    
    # Remove HTML tags
    html_text = re.sub(r'<[^>]+>', '', html_text)
    
    # Decode HTML entities
    html_text = html_text.replace('&nbsp;', ' ')
    html_text = html_text.replace('&amp;', '&')
    html_text = html_text.replace('&lt;', '<')
    html_text = html_text.replace('&gt;', '>')
    html_text = html_text.replace('&quot;', '"')
    html_text = html_text.replace('&apos;', "'")
    
    # Clean up whitespace
    html_text = re.sub(r'\n+', '\n', html_text)
    html_text = re.sub(r'  +', ' ', html_text)
    
    return html_text.strip()


def is_html_content(text: Optional[str]) -> bool:
    """
    Quick check if text contains HTML tags.
    
    Args:
        text: Text to check
        
    Returns:
        True if HTML tags detected
    """
    if not text:
        return False
    text_str = str(text).strip()
    return bool(re.search(r'<[^>]+>', text_str))
