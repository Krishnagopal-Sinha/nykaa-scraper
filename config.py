#!/usr/bin/env python3
"""
Configuration file for Nykaa Scraper

Modify these settings to customize the scraper behavior.
"""

# Scraper Configuration
SCRAPER_CONFIG = {
    # Browser settings
    "headless": True,                    # Run browser in background
    "window_size": "1920,1080",         # Browser window size
    "delay_range": (2, 4),              # Random delay between requests (min, max) seconds
    
    # Scraping limits
    "max_products_per_keyword": 10,     # Maximum products to scrape per keyword
    "max_reviews_per_product": 20,      # Maximum reviews to collect per product
    "max_pages_per_search": 5,          # Maximum search result pages to process
    
    # Output settings
    "output_format": "json",            # Output format: 'json', 'csv' (future)
    "include_images": True,             # Whether to collect product images
    "include_reviews": True,            # Whether to collect product reviews
    "generate_summary": True,           # Whether to generate summary reports
    
    # Logging settings
    "log_level": "INFO",                # Logging level: DEBUG, INFO, WARNING, ERROR
    "log_to_file": True,               # Whether to log to file
    "log_filename": "nykaa_scraper.log" # Log file name
}

# Default keywords to search for
DEFAULT_KEYWORDS = [
    # Makeup products
    "lipstick",
    "foundation",
    "mascara",
    "eyeliner",
    "blush",
    "concealer",
    
    # Skincare products
    "moisturizer",
    "sunscreen",
    "serum",
    "cleanser",
    "toner",
    "face mask",
    
    # Hair care
    "shampoo",
    "conditioner", 
    "hair oil",
    "hair mask",
    
    # Fragrance
    "perfume",
    "deodorant",
    
    # Personal care
    "body lotion",
    "body wash"
]

# Custom keywords for specific categories (optional)
CATEGORY_KEYWORDS = {
    "luxury_makeup": [
        "luxury lipstick",
        "premium foundation",
        "high-end mascara"
    ],
    "organic_skincare": [
        "organic moisturizer",
        "natural cleanser",
        "herbal face pack"
    ],
    "anti_aging": [
        "anti-aging serum",
        "wrinkle cream",
        "collagen cream"
    ]
}

# Product URL patterns (for direct scraping if needed)
NYKAA_URL_PATTERNS = {
    "base_url": "https://www.nykaa.com",
    "search_url": "https://www.nykaa.com/search/result/?q={keyword}",
    "category_urls": {
        "makeup": "https://www.nykaa.com/makeup-c-150",
        "skincare": "https://www.nykaa.com/skin-c-156", 
        "haircare": "https://www.nykaa.com/hair-c-169",
        "fragrance": "https://www.nykaa.com/fragrance-c-173"
    }
}

# CSS Selectors (may need updating if Nykaa changes their website)
CSS_SELECTORS = {
    "product_cards": [
        "[data-testid='product-card']",
        ".product-card", 
        ".nykaa-product-card"
    ],
    "product_links": [
        "[data-testid='product-card'] a",
        ".product-card a",
        ".product-link"
    ],
    "next_page": [
        "[aria-label='Next']",
        ".next-page",
        ".pagination-next"
    ],
    "product_title": [
        "h1",
        ".product-title",
        "[data-testid='product-title']"
    ],
    "product_price": [
        ".price",
        "[data-testid='price']",
        ".product-price"
    ],
    "product_rating": [
        ".rating",
        "[data-testid='rating']", 
        ".star-rating"
    ],
    "reviews_section": [
        ".review-item",
        ".review-card",
        "[data-testid='review']"
    ]
}

# Request headers to mimic real browser
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0"
}

# Chrome browser options
CHROME_OPTIONS = [
    "--no-sandbox",
    "--disable-dev-shm-usage", 
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-plugins",
    "--disable-images",  # Disable image loading for faster scraping
]

# File naming patterns
FILE_PATTERNS = {
    "data_file": "nykaa_scraped_data_{timestamp}.json",
    "summary_file": "nykaa_scraped_data_{timestamp}_summary.txt",
    "log_file": "nykaa_scraper.log",
    "error_file": "nykaa_scraper_errors.log"
} 