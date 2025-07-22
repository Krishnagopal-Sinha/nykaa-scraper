# Nykaa Product Scraper

A comprehensive web scraper for Nykaa.com that collects detailed product information, user reviews, and seller data. This scraper is designed for maximum data collection with a professional, industry-standard approach.

## Features

### 🛍️ Product Information

- Product name, brand, and category details
- Pricing information (regular price, discounted price, discount percentage)
- Product ratings and review counts
- Detailed product descriptions and key features
- Ingredient lists and usage instructions
- Multiple product images
- Product variants (sizes, colors, etc.)
- Availability and stock status
- Delivery and return policy information

### 💬 Reviews & User Data

- Comprehensive review collection with user information
- User verification status and purchase details
- Review ratings, titles, and detailed content
- Review dates and helpfulness metrics
- User-uploaded review images
- Anonymous user handling

### 🏪 Seller & Brand Information

- Seller/brand details and ratings
- Official store verification
- Brand descriptions and additional metadata

### 📊 Technical Features

- Professional logging with file and console output
- Rate limiting and respectful scraping practices
- Error handling and recovery mechanisms
- Progress tracking with progress bars
- Structured JSON output with metadata
- Summary report generation
- Chrome WebDriver automation with anti-detection measures

## Installation

### Prerequisites

- Python 3.8 or higher
- Chrome browser installed
- Stable internet connection

### Setup

1. **Clone or download the project files:**

   ```bash
   # Download the scraper files to your project directory
   ```

2. **Install required dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Verify Chrome installation:**
   The scraper will automatically download and manage ChromeDriver, but ensure Chrome browser is installed on your system.

## Usage

### Basic Usage

1. **Run the scraper with default settings:**

   ```bash
   python nykaa_scraper.py
   ```

2. **The scraper will:**
   - Search for products using predefined keywords
   - Collect comprehensive product data
   - Save results to JSON files with timestamps
   - Generate summary reports

### Customization

You can customize the scraper by modifying the `main()` function in `nykaa_scraper.py`:

```python
# Configuration options
KEYWORDS = [
    "lipstick",
    "foundation",
    "moisturizer",
    # Add your keywords here
]

MAX_PRODUCTS_PER_KEYWORD = 10  # Adjust based on needs
HEADLESS = True  # Set to False to see browser in action
```

### Advanced Usage

```python
from nykaa_scraper import NykaaScraper

# Initialize with custom settings
scraper = NykaaScraper(
    headless=False,        # Show browser window
    delay_range=(3, 6)     # Longer delays between requests
)

# Custom keyword list
custom_keywords = ["organic skincare", "anti-aging serum", "vitamin c"]

# Run scraping
data = scraper.scrape_keywords(custom_keywords, max_products_per_keyword=5)

# Save with custom filename
scraper.save_data("my_custom_scrape_results.json")

# Cleanup
scraper.cleanup()
```

## Output Structure

### JSON File Structure

```json
{
  "scrape_metadata": {
    "scrape_date": "2024-01-15T14:30:00",
    "total_products": 100,
    "total_reviews": 1250,
    "keywords_searched": ["lipstick", "foundation"]
  },
  "products": [
    {
      "product_id": "unique_id",
      "name": "Product Name",
      "brand": "Brand Name",
      "category": "Makeup",
      "subcategory": "Lips",
      "price": 999.0,
      "discounted_price": 799.0,
      "discount_percentage": 20.02,
      "rating": 4.3,
      "review_count": 245,
      "description": "Detailed product description...",
      "key_features": ["Feature 1", "Feature 2"],
      "ingredients": ["Ingredient 1", "Ingredient 2"],
      "how_to_use": "Usage instructions...",
      "images": ["image_url_1", "image_url_2"],
      "variants": [
        {
          "name": "Shade 1",
          "price": 999.0,
          "availability": "In Stock",
          "variant_id": "variant_123"
        }
      ],
      "seller_info": {
        "seller_name": "Seller Name",
        "brand_name": "Brand Name",
        "official_store": true
      },
      "reviews": [
        {
          "user_info": {
            "username": "User123",
            "verified_purchase": true
          },
          "rating": 5,
          "title": "Great product!",
          "content": "Detailed review content...",
          "date": "2024-01-10",
          "helpful_count": 12,
          "images": ["review_image_url"]
        }
      ],
      "specifications": {
        "Net Quantity": "4.5 ml",
        "Finish": "Matte"
      },
      "availability": "In Stock",
      "scraped_at": "2024-01-15T14:35:00",
      "product_url": "https://www.nykaa.com/product/..."
    }
  ]
}
```

### Generated Files

- `nykaa_scraped_data_YYYYMMDD_HHMMSS.json` - Complete scraped data
- `nykaa_scraped_data_YYYYMMDD_HHMMSS_summary.txt` - Summary report
- `nykaa_scraper.log` - Detailed execution logs

## Configuration Options

### Scraper Settings

- **Headless Mode**: Run browser in background (default: True)
- **Delay Range**: Random delays between requests (default: 2-4 seconds)
- **Max Products**: Limit products per keyword (default: 10)
- **Keywords**: Customizable search terms

### Rate Limiting

The scraper includes built-in rate limiting to be respectful to Nykaa's servers:

- Random delays between requests
- Proper browser headers and user agents
- Anti-detection measures

## Data Quality & Coverage

### Product Data Completeness

- ✅ Basic product information (name, price, ratings)
- ✅ Detailed descriptions and features
- ✅ Product images and variants
- ✅ Availability and shipping information
- ✅ Seller and brand details

### Review Data Quality

- ✅ Comprehensive review text and ratings
- ✅ User verification status
- ✅ Review dates and helpfulness metrics
- ✅ User-uploaded images from reviews
- ✅ Anonymous user handling

## Troubleshooting

### Common Issues

1. **Chrome Driver Issues:**

   ```bash
   # Clear browser cache and reinstall webdriver-manager
   pip uninstall webdriver-manager
   pip install webdriver-manager
   ```

2. **Rate Limiting:**

   - Increase delay ranges in configuration
   - Reduce max_products_per_keyword
   - Run scraping during off-peak hours

3. **Element Not Found Errors:**

   - Nykaa may update their HTML structure
   - Check logs for specific selector issues
   - Update selectors in the code if needed

4. **Memory Issues:**
   - Reduce the number of products scraped per session
   - Clear browser cache periodically
   - Restart scraper for large datasets

### Debug Mode

Set `HEADLESS = False` in the configuration to see the browser in action and debug issues.

## Legal and Ethical Considerations

- **Respect robots.txt**: Always check and respect website policies
- **Rate Limiting**: The scraper includes delays to avoid overwhelming servers
- **Personal Use**: Ensure compliance with terms of service
- **Data Privacy**: Handle user data responsibly and in compliance with regulations

## Contributing

This scraper follows professional development standards:

- Comprehensive error handling
- Detailed logging and monitoring
- Modular, maintainable code structure
- Professional documentation

## License

This project is for educational and research purposes. Please ensure compliance with Nykaa's terms of service and applicable laws.

## Support

For issues or questions:

1. Check the log files for detailed error information
2. Review the troubleshooting section
3. Ensure all dependencies are properly installed
4. Verify Chrome browser installation

---

**Note**: This scraper is designed to be respectful of website resources and includes appropriate delays and error handling. Always ensure compliance with website terms of service and applicable laws when using web scraping tools.
