"""
Nykaa Product Scraper

A comprehensive web scraper for Nykaa.com with:
- Large-scale scraping capabilities
- Checkpoint/resume functionality
- Multi-threading optimization
- Semantic-based element detection
- Comprehensive review extraction with proper Load More handling
- Separate JSON files per keyword
"""

import requests
import json
import time
import random
import re
import logging
import os
import threading
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from tqdm import tqdm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nykaa_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ProductVariant:
    """Data class for product variants (size, color, etc.)"""
    name: str
    price: Optional[float]
    discounted_price: Optional[float]
    availability: str
    variant_id: Optional[str]

@dataclass
class UserInfo:
    """Data class for user information from reviews"""
    username: str
    user_id: Optional[str]
    verified_purchase: bool
    review_count: Optional[int]
    location: Optional[str]
    join_date: Optional[str]

@dataclass
class Review:
    """Data class for product reviews"""
    review_id: Optional[str]
    user_info: UserInfo
    rating: int
    title: str
    content: str
    date: str
    helpful_count: int
    verified_purchase: bool
    images: List[str]
    pros: List[str]
    cons: List[str]

@dataclass
class SellerInfo:
    """Data class for seller/brand information"""
    seller_name: str
    seller_id: Optional[str]
    brand_name: str
    brand_id: Optional[str]
    seller_rating: Optional[float]
    seller_reviews_count: Optional[int]
    brand_description: Optional[str]
    official_store: bool

@dataclass
class ProductInfo:
    """Data class for complete product information"""
    product_id: str
    name: str
    brand: str
    category: str
    subcategory: str
    price: float
    discounted_price: Optional[float]
    discount_percentage: Optional[float]
    rating: float
    review_count: int
    description: str
    key_features: List[str]
    ingredients: List[str]
    how_to_use: str
    images: List[str]
    variants: List[ProductVariant]
    seller_info: SellerInfo
    reviews: List[Review]
    specifications: Dict[str, Any]
    tags: List[str]
    availability: str
    delivery_info: str
    return_policy: str
    scraped_at: str
    product_url: str

class CheckpointManager:
    """Manages checkpoint saving and loading for resume functionality"""
    
    def __init__(self, checkpoint_dir: str = "checkpoints"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(checkpoint_dir, exist_ok=True)
    
    def save_checkpoint(self, keyword: str, scraped_products: List[Dict], processed_urls: set, metadata: Dict):
        """Save checkpoint data"""
        checkpoint_data = {
            'keyword': keyword,
            'scraped_products': scraped_products,
            'processed_urls': list(processed_urls),
            'metadata': metadata,
            'timestamp': datetime.now().isoformat()
        }
        
        checkpoint_file = os.path.join(self.checkpoint_dir, f"checkpoint_{keyword.replace(' ', '_')}.pkl")
        try:
            with open(checkpoint_file, 'wb') as f:
                pickle.dump(checkpoint_data, f)
            logger.info(f"Checkpoint saved for keyword '{keyword}': {len(scraped_products)} products")
        except Exception as e:
            logger.error(f"Failed to save checkpoint for '{keyword}': {e}")
    
    def load_checkpoint(self, keyword: str) -> Optional[Dict]:
        """Load checkpoint data"""
        checkpoint_file = os.path.join(self.checkpoint_dir, f"checkpoint_{keyword.replace(' ', '_')}.pkl")
        if os.path.exists(checkpoint_file):
            try:
                with open(checkpoint_file, 'rb') as f:
                    data = pickle.load(f)
                logger.info(f"Checkpoint loaded for keyword '{keyword}': {len(data['scraped_products'])} products")
                return data
            except Exception as e:
                logger.error(f"Failed to load checkpoint for '{keyword}': {e}")
        return None
    
    def clear_checkpoint(self, keyword: str):
        """Clear checkpoint after successful completion"""
        checkpoint_file = os.path.join(self.checkpoint_dir, f"checkpoint_{keyword.replace(' ', '_')}.pkl")
        try:
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                logger.info(f"Checkpoint cleared for keyword '{keyword}'")
        except Exception as e:
            logger.error(f"Failed to clear checkpoint for '{keyword}': {e}")

class NykaaScraper:
    """Main scraper class for Nykaa.com with large-scale optimizations"""
    
    def __init__(self, headless: bool = True, delay_range: tuple = (1, 3), max_threads: int = 2,
                 max_reviews_per_product: int = 200, max_scroll_attempts: int = 150,
                 max_consecutive_no_new: int = 10, review_load_wait_time: int = 8,
                 enable_checkpoints: bool = True, save_frequency: int = 50,
                 output_dir: str = "scrapped-data"):
        """
        Initialize the Nykaa scraper with large-scale optimizations
        """
        self.base_url = "https://www.nykaa.com"
        self.delay_range = delay_range
        self.max_threads = max_threads
        self.max_reviews_per_product = max_reviews_per_product
        self.max_scroll_attempts = max_scroll_attempts
        self.max_consecutive_no_new = max_consecutive_no_new
        self.review_load_wait_time = review_load_wait_time
        self.enable_checkpoints = enable_checkpoints
        self.save_frequency = save_frequency
        self.output_dir = output_dir
        
        # Create output directory
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.ua = UserAgent()
        self.session = requests.Session()
        self.driver = None
        self.headless = headless
        
        # Thread safety
        self._data_lock = Lock()
        self._thread_local = threading.local()
        
        # Checkpoint manager
        self.checkpoint_manager = CheckpointManager() if enable_checkpoints else None
        
        # Setup session headers
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
    def _get_thread_driver(self):
        """Get or create a driver instance for the current thread"""
        if not hasattr(self._thread_local, 'driver') or self._thread_local.driver is None:
            logger.info(f"Creating new driver for thread {threading.current_thread().name}")
            self._thread_local.driver = self._create_driver_instance()
        return self._thread_local.driver
    
    def _create_driver_instance(self):
        """Create a new WebDriver instance with optimized settings"""
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless")
            
            # Optimizations for large-scale scraping
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument(f"--user-agent={self.ua.random}")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Memory optimizations
            chrome_options.add_argument("--memory-pressure-off")
            chrome_options.add_argument("--max_old_space_size=4096")
            
            service = self._get_chromedriver_service()
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver
            
        except Exception as e:
            logger.error(f"Failed to create WebDriver: {e}")
            raise
    
    def _get_chromedriver_service(self):
        """Get ChromeDriver service with simplified setup"""
        if not hasattr(self, '_chromedriver_path'):
            self._chromedriver_path = self._setup_chromedriver()
        return Service(self._chromedriver_path)
    
    def _setup_chromedriver(self):
        """Setup ChromeDriver with automatic detection and download"""
        import platform
        import subprocess
        import stat
        
        # Try system ChromeDriver first
        try:
            result = subprocess.run(['which', 'chromedriver'], capture_output=True, text=True)
            if result.returncode == 0:
                driver_path = result.stdout.strip()
                # Test if it actually works
                test_result = subprocess.run([driver_path, '--version'], capture_output=True, text=True, timeout=5)
                if test_result.returncode == 0:
                    logger.info(f"Using system ChromeDriver: {driver_path}")
                    return driver_path
        except Exception:
            pass
        
        # Try webdriver-manager
        try:
            logger.info("Attempting to install ChromeDriver using webdriver-manager...")
            driver_path = ChromeDriverManager().install()
            logger.info(f"webdriver-manager returned path: {driver_path}")
            
            # The webdriver-manager often returns the wrong file (THIRD_PARTY_NOTICES)
            # We need to find the actual chromedriver executable
            actual_driver_path = None
            
            # Check if the returned path is actually the executable
            if (os.path.isfile(driver_path) and 
                os.access(driver_path, os.X_OK) and 
                not driver_path.endswith('THIRD_PARTY_NOTICES.chromedriver')):
                try:
                    test_result = subprocess.run([driver_path, '--version'], capture_output=True, text=True, timeout=5)
                    if test_result.returncode == 0:
                        actual_driver_path = driver_path
                except Exception:
                    pass
            
            # If the returned path is wrong, search for the actual executable
            if not actual_driver_path:
                logger.info("Searching for actual ChromeDriver executable...")
                
                # Get the directory containing the ChromeDriver
                search_dir = os.path.dirname(driver_path)
                
                # Go up directories to find the base cache directory
                for _ in range(3):
                    if os.path.basename(search_dir) == '.wdm' or 'chromedriver' in os.path.basename(search_dir):
                        break
                    search_dir = os.path.dirname(search_dir)
                
                logger.info(f"Searching in directory: {search_dir}")
                
                # Search for chromedriver executable recursively
                for root, dirs, files in os.walk(search_dir):
                    for file in files:
                        if file == 'chromedriver':
                            potential_path = os.path.join(root, file)
                            
                            # Skip text files and notices
                            if ('THIRD_PARTY_NOTICES' in potential_path or 
                                potential_path.endswith('.txt') or
                                potential_path.endswith('.chromedriver')):
                                continue
                            
                            if os.path.isfile(potential_path):
                                # Make it executable
                                try:
                                    os.chmod(potential_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                                except Exception:
                                    continue
                                
                                # Test if it's a working executable
                                try:
                                    test_result = subprocess.run([potential_path, '--version'], 
                                                               capture_output=True, text=True, timeout=5)
                                    if test_result.returncode == 0:
                                        logger.info(f"Found working ChromeDriver: {potential_path}")
                                        actual_driver_path = potential_path
                                        break
                                except Exception as e:
                                    logger.debug(f"Test failed for {potential_path}: {e}")
                                    continue
                    if actual_driver_path:
                        break
            
            if actual_driver_path:
                logger.info(f"Using ChromeDriver: {actual_driver_path}")
                return actual_driver_path
            else:
                logger.warning("Could not find working ChromeDriver executable in webdriver-manager cache")
            
        except Exception as e:
            logger.warning(f"webdriver-manager failed: {e}")
        
        # Manual download as last resort
        logger.info("Attempting manual ChromeDriver download...")
        try:
            return self._manual_chromedriver_download()
        except Exception as e:
            logger.error(f"Manual ChromeDriver download failed: {e}")
        
        raise Exception("Could not setup ChromeDriver - all methods failed")
    
    def _manual_chromedriver_download(self):
        """Manually download ChromeDriver as last resort"""
        import platform
        import subprocess
        import requests
        import zipfile
        import stat
        
        # Determine platform
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        if system == "darwin":
            if "arm" in machine or "aarch64" in machine:
                platform_name = "mac-arm64"
            else:
                platform_name = "mac-x64"
        elif system == "linux":
            if "arm" in machine or "aarch64" in machine:
                platform_name = "linux-arm64"
            else:
                platform_name = "linux64"
        else:  # Windows
            platform_name = "win64"
        
        # Create drivers directory
        drivers_dir = os.path.join(os.getcwd(), "drivers")
        os.makedirs(drivers_dir, exist_ok=True)
        
        # Try recent stable versions
        stable_versions = [
            "131.0.6778.85",
            "131.0.6778.69", 
            "130.0.6723.116",
            "130.0.6723.91",
            "129.0.6668.100"
        ]
        
        for version in stable_versions:
            try:
                download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform_name}/chromedriver-{platform_name}.zip"
                
                logger.info(f"Trying ChromeDriver version {version} for {platform_name}")
                
                # Download
                response = requests.get(download_url, timeout=30)
                if response.status_code != 200:
                    continue
                
                # Save and extract
                zip_path = os.path.join(drivers_dir, f"chromedriver_{version}.zip")
                with open(zip_path, "wb") as f:
                    f.write(response.content)
                
                # Extract
                extract_dir = os.path.join(drivers_dir, f"chromedriver_{version}")
                os.makedirs(extract_dir, exist_ok=True)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                
                # Find chromedriver executable
                driver_path = None
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file == 'chromedriver':
                            potential_path = os.path.join(root, file)
                            if os.path.isfile(potential_path):
                                driver_path = potential_path
                                break
                    if driver_path:
                        break
                
                if driver_path and os.path.isfile(driver_path):
                    # Make executable
                    os.chmod(driver_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                    
                    # Test if it works
                    test_result = subprocess.run([driver_path, '--version'], capture_output=True, text=True, timeout=10)
                    if test_result.returncode == 0:
                        logger.info(f"Successfully downloaded and verified ChromeDriver {version}: {driver_path}")
                        
                        # Clean up zip file
                        try:
                            os.remove(zip_path)
                        except:
                            pass
                        
                        return driver_path
                
                # Clean up failed attempt
                try:
                    os.remove(zip_path)
                    import shutil
                    shutil.rmtree(extract_dir)
                except:
                    pass
                
            except Exception as e:
                logger.warning(f"Failed to download ChromeDriver version {version}: {e}")
                continue
        
        raise Exception("Could not download any working ChromeDriver version")
    
    def random_delay(self):
        """Add random delay between requests"""
        delay = random.uniform(*self.delay_range)
        time.sleep(delay)
    
    def _scrape_keyword_with_checkpoint(self, keyword: str, max_products: int) -> Dict[str, Any]:
        """Scrape products for a keyword with checkpoint support and separate file saving"""
        thread_name = threading.current_thread().name
        logger.info(f"[{thread_name}] Starting keyword: '{keyword}' (max: {max_products} products)")
        
        # Load checkpoint if available
        processed_urls = set()
        scraped_products = []
        
        if self.checkpoint_manager:
            checkpoint_data = self.checkpoint_manager.load_checkpoint(keyword)
            if checkpoint_data:
                scraped_products = checkpoint_data.get('scraped_products', [])
                processed_urls = set(checkpoint_data.get('processed_urls', []))
                logger.info(f"[{thread_name}] Resuming from checkpoint: {len(scraped_products)} products already scraped")
        
        try:
            driver = self._get_thread_driver()
            
            # Get product URLs
            product_urls = self._search_products_optimized(driver, keyword, max_products)
            
            # Filter out already processed URLs
            new_urls = [url for url in product_urls if url not in processed_urls]
            logger.info(f"[{thread_name}] Found {len(product_urls)} total URLs, {len(new_urls)} new URLs")
            
            # Process new URLs
            for i, url in enumerate(new_urls):
                if len(scraped_products) >= max_products:
                    break
                
                try:
                    logger.info(f"[{thread_name}] Scraping product {len(scraped_products)+1}/{max_products}: {url}")
                    product_info = self._scrape_product_details_optimized(driver, url)
                    
                    if product_info:
                        scraped_products.append(asdict(product_info))
                        processed_urls.add(url)
                        
                        # Save checkpoint periodically
                        if (self.checkpoint_manager and 
                            len(scraped_products) % self.save_frequency == 0):
                            self.checkpoint_manager.save_checkpoint(
                                keyword, scraped_products, processed_urls, 
                                {'total_urls': len(product_urls), 'processed': len(processed_urls)}
                            )
                    
                    self.random_delay()
                    
                except Exception as e:
                    logger.error(f"[{thread_name}] Error scraping {url}: {e}")
                    continue
            
            # Create keyword-specific data structure
            keyword_data = {
                'scrape_metadata': {
                    'scrape_date': datetime.now().isoformat(),
                    'keyword': keyword,
                    'total_products': len(scraped_products),
                    'total_reviews': sum(len(p.get('reviews', [])) for p in scraped_products),
                    'scraper_version': '2.0_optimized'
                },
                'products': scraped_products
            }
            
            # Save separate JSON file for this keyword
            self._save_keyword_data(keyword, keyword_data)
            
            # Clear checkpoint on successful completion
            if self.checkpoint_manager:
                self.checkpoint_manager.clear_checkpoint(keyword)
            
            logger.info(f"[{thread_name}] Completed '{keyword}': {len(scraped_products)} products")
            return keyword_data
            
        except Exception as e:
            logger.error(f"[{thread_name}] Error processing keyword '{keyword}': {e}")
            # Return partial data if available
            keyword_data = {
                'scrape_metadata': {
                    'scrape_date': datetime.now().isoformat(),
                    'keyword': keyword,
                    'total_products': len(scraped_products),
                    'total_reviews': sum(len(p.get('reviews', [])) for p in scraped_products),
                    'scraper_version': '2.0_optimized',
                    'error': str(e)
                },
                'products': scraped_products
            }
            return keyword_data
    
    def _save_keyword_data(self, keyword: str, data: Dict[str, Any]):
        """Save data for a specific keyword to a separate JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_keyword = keyword.replace(' ', '_').replace('/', '_')
        filename = f"{safe_keyword}_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # Also save CSV summary for this keyword
            csv_filename = f"{safe_keyword}_{timestamp}.csv"
            csv_filepath = os.path.join(self.output_dir, csv_filename)
            self._save_csv_summary(data, csv_filepath)
            
            logger.info(f"Data saved for keyword '{keyword}': {filepath} and {csv_filepath}")
                        
        except Exception as e:
            logger.error(f"Error saving data for keyword '{keyword}': {e}")
    
    def _save_csv_summary(self, data: Dict[str, Any], filepath: str):
        """Save a CSV summary for a specific keyword"""
        try:
            import pandas as pd
            
            # Create summary data
            summary_data = []
            for product in data['products']:
                summary_data.append({
                    'product_id': product.get('product_id', ''),
                    'name': product.get('name', ''),
                    'brand': product.get('brand', ''),
                    'category': product.get('category', ''),
                    'price': product.get('price', 0),
                    'discounted_price': product.get('discounted_price', ''),
                    'rating': product.get('rating', 0),
                    'review_count': product.get('review_count', 0),
                    'reviews_scraped': len(product.get('reviews', [])),
                    'availability': product.get('availability', ''),
                    'product_url': product.get('product_url', '')
                })
            
            df = pd.DataFrame(summary_data)
            df.to_csv(filepath, index=False)
            
        except ImportError:
            logger.info("Pandas not available, skipping CSV export")
        except Exception as e:
            logger.error(f"Error saving CSV: {e}")
    
    def _search_products_optimized(self, driver, keyword: str, max_products: int) -> List[str]:
        """Optimized product search with better pagination handling"""
        logger.info(f"Searching for products: '{keyword}' (max: {max_products})")
        
        product_urls = []
        
        try:
            # Start with page 1
            page_num = 1
            
            while len(product_urls) < max_products:
                # Build URL with page number parameter
                search_url = f"{self.base_url}/search/result/?q={keyword.replace(' ', '%20')}&page_no={page_num}&sort=popularity"
                logger.info(f"Scraping search page {page_num} for '{keyword}': {search_url}")
                
                driver.get(search_url)
                self.random_delay()
                
                # Wait for products to load
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/p/']"))
                    )
                except TimeoutException:
                    logger.warning(f"No products found on page {page_num}")
                    # Check if we've reached the end by looking for "no results" indicators
                    page_source = driver.page_source.lower()
                    if any(indicator in page_source for indicator in ['no products found', 'no results', 'sorry', '0 products']):
                        logger.info(f"Reached end of results at page {page_num}")
                        break
                    # If it's just a timeout, try next page
                    if page_num == 1:
                        break  # If first page fails, something is wrong
                    page_num += 1
                    continue
                
                # Extract product URLs using semantic selectors
                product_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/p/']")
                
                new_urls_count = 0
                for link in product_links:
                    if len(product_urls) >= max_products:
                        break
                    
                    try:
                        product_url = link.get_attribute('href')
                        if product_url and '/p/' in product_url and product_url not in product_urls:
                            # Clean URL - remove query parameters
                            if '?' in product_url:
                                product_url = product_url.split('?')[0]
                            product_urls.append(product_url)
                            new_urls_count += 1
                    except Exception:
                        continue
                
                logger.info(f"Page {page_num}: Found {new_urls_count} new product URLs (total: {len(product_urls)})")
                
                # If no new products found on this page, we've reached the end
                if new_urls_count == 0:
                    logger.info(f"No new products found on page {page_num}, stopping pagination")
                    break
                
                # Check if we've reached max products
                if len(product_urls) >= max_products:
                    logger.info(f"Reached maximum products limit ({max_products})")
                    break
                
                # Move to next page
                page_num += 1
                
                # Safety check to prevent infinite loops
                if page_num > 100:  # Reasonable safety limit
                    logger.warning(f"Reached safety limit of 100 pages for keyword '{keyword}'")
                    break
        
        except Exception as e:
            logger.error(f"Error during product search: {e}")
        
        logger.info(f"Search completed for '{keyword}': {len(product_urls)} URLs found across {page_num-1} pages")
        return product_urls[:max_products]
    
    def _scrape_product_details_optimized(self, driver, product_url: str) -> Optional[ProductInfo]:
        """Optimized product detail scraping"""
        try:
            driver.get(product_url)
            self.random_delay()
            
            # Wait for basic content
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .product-title"))
            )
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract basic info (simplified for speed)
            product_info = self._extract_basic_info_fast(soup, product_url)
            if not product_info:
                return None
            
            # Extract reviews with optimized method
            if self.max_reviews_per_product > 0:
                product_info.reviews = self._extract_reviews_with_load_more(driver, product_url)
            
            product_info.scraped_at = datetime.now().isoformat()
            return product_info
            
        except Exception as e:
            logger.error(f"Error scraping product {product_url}: {e}")
            return None
    
    def _extract_basic_info_fast(self, soup: BeautifulSoup, product_url: str) -> Optional[ProductInfo]:
        """Fast extraction of basic product information"""
        try:
            # Extract from JSON data (fastest method)
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'window.__PRELOADED_STATE__' in script.string:
                    try:
                        json_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});', script.string)
                        if json_match:
                            data = json.loads(json_match.group(1))
                            product_details = data.get('productPage', {}).get('productDetails', {})
                            if product_details.get('name'):
                                return self._create_product_info_from_json(product_details, product_url)
                    except Exception:
                        continue
            
            # Fallback to HTML extraction
            return self._extract_basic_info_from_html(soup, product_url)
            
        except Exception as e:
            logger.error(f"Error extracting basic info: {e}")
            return None

    def _create_product_info_from_json(self, data: dict, product_url: str) -> ProductInfo:
        """Create ProductInfo from JSON data"""
        return ProductInfo(
            product_id=str(data.get('parentId', data.get('id', 'unknown'))),
            name=data.get('name', 'Unknown Product'),
            brand=data.get('brandName', 'Unknown Brand'),
            category=data.get('primaryCategories', {}).get('l2', {}).get('name', 'Unknown'),
            subcategory=data.get('primaryCategories', {}).get('l3', {}).get('name', 'Unknown'),
            price=float(data.get('mrp', 0)),
            discounted_price=float(data.get('offerPrice', 0)) if data.get('offerPrice') else None,
            discount_percentage=float(data.get('discount', 0)) if data.get('discount') else None,
            rating=float(data.get('rating', 0)),
            review_count=int(data.get('reviewCount', 0)),
            description=data.get('description', ''),
            key_features=[],
            ingredients=[],
            how_to_use='',
            images=[data.get('imageUrl', '')] if data.get('imageUrl') else [],
            variants=[],
            seller_info=SellerInfo('', None, data.get('brandName', ''), None, None, None, None, False),
            reviews=[],
            specifications={},
            tags=[],
            availability="In Stock" if data.get('inStock', False) else "Out of Stock",
            delivery_info='',
            return_policy='',
            scraped_at='',
            product_url=product_url
        )
            
    def _extract_basic_info_from_html(self, soup: BeautifulSoup, product_url: str) -> Optional[ProductInfo]:
        """HTML fallback extraction"""
        try:
            name = self._get_text_by_selectors(soup, ['h1', '.product-title'], "Unknown Product")
            brand = self._get_text_by_selectors(soup, ['.brand-name'], "Unknown Brand")
            
            return ProductInfo(
                product_id=self._extract_product_id_from_url(product_url),
                name=name,
                brand=brand,
                category="Unknown",
                subcategory="Unknown",
                price=0.0,
                discounted_price=None,
                discount_percentage=None,
                rating=0.0,
                review_count=0,
                description="",
                key_features=[],
                ingredients=[],
                how_to_use="",
                images=[],
                variants=[],
                seller_info=SellerInfo("", None, brand, None, None, None, None, False),
                reviews=[],
                specifications={},
                tags=[],
                availability="Unknown",
                delivery_info="",
                return_policy="",
                scraped_at="",
                product_url=product_url
            )
        except Exception:
            return None

    def _extract_reviews_with_load_more(self, driver, product_url: str) -> List[Review]:
        """Enhanced review extraction with proper Load More button handling and JSON parsing"""
        reviews = []
        
        try:
            # Navigate to reviews page
            product_id = self._extract_product_id_from_url(product_url)
            if not product_id:
                return reviews
            
            # Build reviews URL
            product_slug = self._extract_product_slug(product_url)
            if product_slug:
                reviews_url = f"{self.base_url}/{product_slug}/reviews/{product_id}?ptype=reviews"
            else:
                reviews_url = f"{product_url}/reviews"
            
            logger.info(f"Extracting reviews from: {reviews_url}")
            driver.get(reviews_url)
            
            # Wait for initial content to load
            time.sleep(self.review_load_wait_time)
            
            # Handle popups
            self._handle_review_page_popups(driver)
            
            # Extract initial reviews from JSON data
            seen_reviews = set()
            initial_reviews = self._extract_reviews_from_json(driver)
            
            for review in initial_reviews:
                review_id = f"{review.user_info.username}_{review.rating}_{review.content[:50]}_{review.date}"
                if review_id not in seen_reviews:
                    seen_reviews.add(review_id)
                    reviews.append(review)
            
            logger.info(f"Extracted {len(reviews)} initial reviews from JSON data")
            
            # Now try to load more reviews by scrolling and clicking Load More
            load_more_attempts = 0
            max_load_more_attempts = 50
            consecutive_no_new = 0
            
            while (load_more_attempts < max_load_more_attempts and 
                   consecutive_no_new < self.max_consecutive_no_new and
                   len(reviews) < self.max_reviews_per_product):
                
                # Scroll to bottom to trigger Load More button
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(3)  # Wait for button to appear
                
                # Try to click Load More button
                load_more_clicked = self._click_load_more_button(driver)
                
                if load_more_clicked:
                    load_more_attempts += 1
                    logger.info(f"Clicked Load More button (attempt {load_more_attempts})")
                    
                    # Wait for new content to load
                    time.sleep(5)
                    
                    # Extract new reviews from updated JSON data
                    current_reviews = self._extract_reviews_from_json(driver)
                    new_count = 0
                    
                    for review in current_reviews:
                        review_id = f"{review.user_info.username}_{review.rating}_{review.content[:50]}_{review.date}"
                        if review_id not in seen_reviews:
                            seen_reviews.add(review_id)
                            reviews.append(review)
                            new_count += 1
                    
                    logger.info(f"Extracted {new_count} new reviews after Load More (total: {len(reviews)})")
                    
                    if new_count == 0:
                        consecutive_no_new += 1
                    else:
                        consecutive_no_new = 0
                    
                else:
                    # No Load More button found, try scrolling a bit more
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        logger.info("No Load More button found and no new reviews - stopping")
                        break
                    
                    # Try additional scrolling strategies
                    driver.execute_script("window.scrollBy(0, window.innerHeight);")
                    time.sleep(2)
            
            logger.info(f"Review extraction completed: {len(reviews)} total reviews")
            logger.info(f"Load More clicks: {load_more_attempts}")
        
        except Exception as e:
            logger.error(f"Error extracting reviews: {e}")
        
        return reviews[:self.max_reviews_per_product]

    def _extract_reviews_from_json(self, driver) -> List[Review]:
        """Extract reviews from the embedded JSON data in page source"""
        reviews = []
        
        try:
            page_source = driver.page_source
            
            # Find the start of the reviews array using a simpler, more reliable method
            start_pattern = r'"getReviews":\s*\{\s*"Reviews":\s*\{\s*"reviews":\s*\['
            start_match = re.search(start_pattern, page_source)
            
            if start_match:
                start_pos = start_match.end()
                logger.debug(f"Found reviews array start at position {start_pos}")
                
                # Find the matching closing bracket for the reviews array
                bracket_count = 1  # We already have the opening [
                end_pos = start_pos
                
                for i, char in enumerate(page_source[start_pos:], start_pos):
                    if char == '[':
                        bracket_count += 1
                    elif char == ']':
                        bracket_count -= 1
                        if bracket_count == 0:
                            end_pos = i
                            break
                
                if end_pos > start_pos:
                    reviews_json = page_source[start_pos:end_pos]
                    logger.debug(f"Extracted reviews JSON, length: {len(reviews_json)}")
                    
                    try:
                        # Parse the reviews array
                        reviews_data = json.loads('[' + reviews_json + ']')
                        logger.debug(f"Successfully parsed {len(reviews_data)} reviews from JSON")
                        
                        for review_data in reviews_data:
                            review = self._parse_review_from_json(review_data)
                            if review:
                                reviews.append(review)
                        
                        return reviews
                    except json.JSONDecodeError as e:
                        logger.debug(f"Error parsing reviews JSON: {e}")
                else:
                    logger.debug("Could not find end of reviews array")
            else:
                logger.debug("Could not find reviews array start pattern")
            
            # Fallback: try alternative patterns
            logger.debug("Trying fallback patterns...")
            
            # Try to find any reviews data in alternative locations
            alternative_patterns = [
                r'"reviews":\s*\[([^\]]+)\]',
                r'"reviewsList":\s*\[([^\]]+)\]',
                r'"latestReviews":\s*\[([^\]]+)\]'
            ]
            
            for pattern in alternative_patterns:
                match = re.search(pattern, page_source, re.DOTALL)
                if match:
                    try:
                        reviews_json = '[' + match.group(1) + ']'
                        reviews_data = json.loads(reviews_json)
                        
                        logger.debug(f"Found {len(reviews_data)} reviews using fallback pattern")
                        
                        for review_data in reviews_data:
                            review = self._parse_review_from_json(review_data)
                            if review:
                                reviews.append(review)
                        
                        if reviews:
                            return reviews
                    except json.JSONDecodeError:
                        continue
        
        except Exception as e:
            logger.error(f"Error extracting reviews from JSON: {e}")
        
        logger.debug(f"Extracted {len(reviews)} reviews from JSON")
        return reviews
    
    def _clean_json_text(self, json_text: str) -> str:
        """Clean JSON text to ensure it's valid"""
        try:
            # Remove any trailing commas before closing brackets/braces
            json_text = re.sub(r',\s*([}\]])', r'\1', json_text)
            
            # Ensure proper bracket matching
            open_brackets = json_text.count('[')
            close_brackets = json_text.count(']')
            open_braces = json_text.count('{')
            close_braces = json_text.count('}')
            
            # Add missing closing brackets/braces
            if open_brackets > close_brackets:
                json_text += ']' * (open_brackets - close_brackets)
            if open_braces > close_braces:
                json_text += '}' * (open_braces - close_braces)
            
            return json_text
        except Exception:
            return json_text

    def _parse_review_from_json(self, review_data: dict) -> Optional[Review]:
        """Parse a single review from JSON data"""
        try:
            # Extract username
            username = review_data.get('name', review_data.get('userName', 'Anonymous'))
            
            # Extract rating
            rating = int(review_data.get('rating', 0))
            
            # Extract title
            title = review_data.get('title', '')
            
            # Extract content/description
            content = review_data.get('description', review_data.get('content', ''))
            
            # Extract date
            date = review_data.get('createdOn', review_data.get('date', ''))
            # Clean date format
            if date and len(date) > 10:
                date = date.split(' ')[0]  # Keep only the date part
            
            # Extract helpful count
            helpful_count = int(review_data.get('likeCount', 0))
            
            # Extract verified buyer status
            verified_purchase = review_data.get('label') == 'Verified Buyer' or review_data.get('isBuyer', False)
            
            # Only create review if we have minimum required info
            if rating > 0 and (content or title) and username != 'Anonymous':
                return Review(
                    review_id=review_data.get('id'),
                    user_info=UserInfo(username, None, verified_purchase, None, None, None),
                    rating=rating,
                    title=title,
                    content=content,
                    date=date,
                    helpful_count=helpful_count,
                    verified_purchase=verified_purchase,
                    images=[],
                    pros=[],
                    cons=[]
                )
        except Exception as e:
            logger.debug(f"Error parsing review from JSON: {e}")
        
        return None

    def _click_load_more_button(self, driver) -> bool:
        """Click the Load More button with enhanced detection and error handling"""
        
        # List of selectors to try for Load More button (most specific first)
        load_more_selectors = [
            # Specific selectors based on the provided HTML structure
            ".css-1a51j15 button.css-u04n34",
            "div[class*='css-1a51j15'] button[class*='css-u04n34']",
            "button.css-u04n34",
            ".css-1a51j15 button",
            
            # Generic Load More selectors as fallback
            "button[class*='load-more']",
            "button[class*='Load']",
            ".load-more-reviews button",
            ".load-more button",
            "button[aria-label*='Load More']",
            "button[aria-label*='load more']",
            
            # Text-based XPath selectors (most reliable)
            "//button[contains(text(), 'Load More')]",
            "//button[contains(text(), 'LOAD MORE')]", 
            "//button[contains(text(), 'Show More')]",
            "//button[contains(text(), 'View More')]",
            "//button[contains(text(), 'More Reviews')]",
            "//a[contains(text(), 'Load More')]",
            "//a[contains(text(), 'Show More')]",
            
            # Generic button patterns
            "//button[contains(@class, 'load') or contains(@class, 'more')]",
            "//div[contains(@class, 'load-more')]//button",
        ]
        
        for selector in load_more_selectors:
            try:
                if selector.startswith("//"):
                    # XPath selector
                    buttons = driver.find_elements(By.XPATH, selector)
                else:
                    # CSS selector  
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                
                for button in buttons:
                    try:
                        # Check if button is visible and enabled
                        if button.is_displayed() and button.is_enabled():
                            # Check button text to confirm it's the right button
                            button_text = button.text.lower().strip()
                            if any(keyword in button_text for keyword in ['load more', 'show more', 'view more', 'more reviews']):
                                # Scroll to button to ensure it's in view
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", button)
                                time.sleep(1)
                                
                                # Wait for button to be clickable
                                try:
                                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable(button))
                                except TimeoutException:
                                    pass
                                
                                # Try different click methods
                                try:
                                    # Method 1: Regular click
                                    button.click()
                                    logger.info(f"Successfully clicked Load More button using selector: {selector}")
                                    return True
                                except Exception:
                                    try:
                                        # Method 2: JavaScript click
                                        driver.execute_script("arguments[0].click();", button)
                                        logger.info(f"Successfully clicked Load More button via JavaScript using selector: {selector}")
                                        return True
                                    except Exception:
                                        continue
                    except Exception as e:
                        logger.debug(f"Failed to click button with selector {selector}: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error finding button with selector {selector}: {e}")
                continue
        
        # If no Load More button found, try looking for pagination or infinite scroll indicators
        try:
            # Look for any buttons that might trigger more content loading
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            for button in all_buttons:
                try:
                    if button.is_displayed() and button.is_enabled():
                        button_text = button.text.lower().strip()
                        if any(keyword in button_text for keyword in ['load', 'more', 'show', 'next']):
                            logger.info(f"Found potential load more button with text: '{button.text}'")
                            # Attempt to click it
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", button)
                            logger.info(f"Clicked potential Load More button: '{button.text}'")
                            return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Error in fallback button search: {e}")
        
        return False

    def _handle_review_page_popups(self, driver):
        """Handle popups that might appear on review pages"""
        popup_selectors = [
            "button[aria-label='Close']",
            ".popup-close",
            ".modal-close", 
            ".close-btn",
            "//button[contains(text(), 'Close')]",
            "//button[contains(text(), 'Skip')]",
        ]
        
        for selector in popup_selectors:
            try:
                if selector.startswith("//"):
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                
                for element in elements:
                    if element.is_displayed():
                        element.click()
                        logger.info("Closed popup on review page")
                        time.sleep(1)
                        return
            except Exception:
                continue

    def _scroll_for_reviews(self, driver):
        """Scroll page to trigger lazy loading of reviews"""
        try:
            # Multiple scroll strategies
            
            # 1. Scroll to bottom
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            # 2. Scroll by viewport height
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            time.sleep(1)
            
            # 3. Smooth scroll to bottom
            driver.execute_script("""
                window.scrollTo({
                    top: document.body.scrollHeight,
                    behavior: 'smooth'
                });
            """)
            time.sleep(2)
            
        except Exception as e:
            logger.debug(f"Error during scrolling: {e}")

    def _extract_reviews_from_current_page(self, driver) -> List[Review]:
        """Extract reviews from current page state using semantic selectors"""
        reviews = []
        
        try:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Strategy 1: Find by "Verified Buyers" text
            verified_elements = soup.find_all(text=re.compile(r'Verified Buyer', re.I))
            
            for text_elem in verified_elements[:50]:  # Limit to prevent excessive processing
                try:
                    # Navigate up to find review container
                    container = text_elem.parent
                    for _ in range(8):  # Look up to 8 levels up
                        if container and container.name in ['div', 'section', 'article']:
                            content_text = container.get_text(strip=True)
                            # Check if this looks like a review container
                            if (len(content_text) > 50 and 
                                any(keyword in content_text.lower() for keyword in ['star', 'rating', 'review', 'helpful'])):
                                review = self._parse_review_semantic(container)
                                if review:
                                    reviews.append(review)
                                    break
                        container = container.parent if container else None
                except Exception:
                    continue
            
            # Strategy 2: Find by star ratings if not enough reviews
            if len(reviews) < 10:
                star_elements = soup.find_all(['svg', 'span'], class_=re.compile(r'star|rating', re.I))
                for star_elem in star_elements[:30]:
                    try:
                        container = star_elem.parent
                        for _ in range(6):
                            if container and container.name in ['div', 'section', 'article']:
                                content_text = container.get_text(strip=True)
                                if (len(content_text) > 100 and 
                                    'verified' in content_text.lower()):
                                    review = self._parse_review_semantic(container)
                                    if review and not any(r.user_info.username == review.user_info.username and 
                                                        r.content == review.content for r in reviews):
                                        reviews.append(review)
                                        break
                            container = container.parent if container else None
                    except Exception:
                        continue
        
        except Exception as e:
            logger.debug(f"Error extracting reviews from page: {e}")
        
        logger.debug(f"Extracted {len(reviews)} reviews from current page state")
        return reviews

    def _parse_review_semantic(self, container) -> Optional[Review]:
        """Parse review using semantic analysis with improved extraction"""
        try:
            text = container.get_text()
            
            # Extract username (look for text before "Verified Buyer")
            username_match = re.search(r'(.+?)\s+Verified Buyer', text, re.I)
            if username_match:
                username = username_match.group(1).strip()
                # Clean username (remove extra text)
                username = re.sub(r'^\s*avatar\s*', '', username, flags=re.I)
                username = username.split('\n')[0].strip()
            else:
                username = "Anonymous"
            
            # Extract rating (look for star patterns)
            rating = 0
            star_patterns = [
                r'(\d+)\s*star',
                r'rating.*?(\d+)',
                r'(\d+)\s*/\s*5',
                r'★{1,5}',  # Count star symbols
            ]
            
            for pattern in star_patterns:
                match = re.search(pattern, text, re.I)
                if match:
                    if pattern == r'★{1,5}':
                        rating = len(match.group(0))
                    else:
                        rating = int(match.group(1))
                    break
            
            # Extract title (often in quotes or headers)
            title = ""
            title_patterns = [
                r'"([^"]+)"',
                r'\'([^\']+)\'',
                r'Review:\s*(.+?)(?:\n|\.|$)',
            ]
            
            for pattern in title_patterns:
                match = re.search(pattern, text)
                if match:
                    title = match.group(1).strip()
                    if len(title) > 5 and len(title) < 100:  # Reasonable title length
                        break
            
            # Extract content (main review text)
            content = ""
            lines = text.split('\n')
            content_lines = []
            
            for line in lines:
                line = line.strip()
                # Skip metadata lines
                if (len(line) > 20 and 
                    not any(skip in line.lower() for skip in [
                        'verified buyer', 'helpful', 'star', 'rating', 'avatar',
                        'read more', 'show more', 'report', 'share'
                    ])):
                    content_lines.append(line)
            
            content = ' '.join(content_lines[:3])  # Take first 3 content lines
            
            # Clean content
            content = re.sub(r'\s+', ' ', content).strip()
            
            # Extract date
            date = ""
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{1,2}/\d{1,2}/\d{2})',
                r'(\d{1,2}-\d{1,2}-\d{4})',
                r'(\d{4}-\d{1,2}-\d{1,2})',
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    date = match.group(1)
                    break
            
            # Extract helpful count
            helpful_count = 0
            helpful_patterns = [
                r'(\d+)\s*people found this helpful',
                r'(\d+)\s*found.*?helpful',
                r'helpful\s*[:\-]?\s*(\d+)',
            ]
            
            for pattern in helpful_patterns:
                match = re.search(pattern, text, re.I)
                if match:
                    helpful_count = int(match.group(1))
                    break
            
            # Only create review if we have minimum required info
            if rating > 0 and (content or title) and username != "Anonymous":
                return Review(
                    review_id=None,
                    user_info=UserInfo(username, None, True, None, None, None),
                    rating=rating,
                    title=title,
                    content=content,
                    date=date,
                    helpful_count=helpful_count,
                    verified_purchase=True,
                    images=[],
                    pros=[],
                    cons=[]
                )
        except Exception as e:
            logger.debug(f"Error parsing review: {e}")
        
        return None
    
    def _extract_product_id_from_url(self, url: str) -> str:
        """Extract product ID from URL"""
        match = re.search(r'/p/(\d+)', url)
        return match.group(1) if match else "unknown"
    
    def _extract_product_slug(self, url: str) -> Optional[str]:
        """Extract product slug from URL"""
        try:
            path = url.replace(self.base_url, '').strip('/')
            if '/p/' in path:
                return path.split('/p/')[0]
        except Exception:
            pass
        return None
    
    def _get_text_by_selectors(self, soup, selectors: List[str], default: str = "") -> str:
        """Get text using CSS selectors"""
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if text:
                    return text
        return default
    
    def scrape_keywords(self, keywords: List[str], max_products_per_keyword: int = 50) -> Dict[str, Any]:
        """Main method to scrape multiple keywords with separate file saving"""
        logger.info(f"Starting optimized scrape for {len(keywords)} keywords with {self.max_threads} threads")
        logger.info(f"Each keyword will be saved to a separate file in '{self.output_dir}' folder")
        
        # Summary data for final report
        summary_data = {
            'scrape_metadata': {
                'scrape_date': datetime.now().isoformat(),
                'total_keywords': len(keywords),
                'keywords_searched': keywords,
                'scraper_version': '2.0_optimized_fixed'
            },
            'keyword_summaries': []
        }
        
        # Optimize threads
        effective_threads = 1 if len(keywords) == 1 else min(self.max_threads, len(keywords))
        
        with ThreadPoolExecutor(max_workers=effective_threads, thread_name_prefix="NykaaScraper") as executor:
            future_to_keyword = {
                executor.submit(self._scrape_keyword_with_checkpoint, keyword, max_products_per_keyword): keyword
                for keyword in keywords
            }
            
            for future in tqdm(as_completed(future_to_keyword), total=len(keywords), desc="Scraping keywords"):
                keyword = future_to_keyword[future]
                try:
                    keyword_data = future.result()
                    logger.info(f"Completed '{keyword}': {keyword_data['scrape_metadata']['total_products']} products")
                    
                    # Add to summary
                    summary_data['keyword_summaries'].append({
                        'keyword': keyword,
                        'total_products': keyword_data['scrape_metadata']['total_products'],
                        'total_reviews': keyword_data['scrape_metadata']['total_reviews']
                    })
                
                except Exception as e:
                    logger.error(f"Error processing keyword '{keyword}': {e}")
                    summary_data['keyword_summaries'].append({
                        'keyword': keyword,
                        'total_products': 0,
                        'total_reviews': 0,
                        'error': str(e)
                    })
        
        # Save summary report
        self._save_summary_report(summary_data)
        
        total_products = sum(s['total_products'] for s in summary_data['keyword_summaries'])
        total_reviews = sum(s['total_reviews'] for s in summary_data['keyword_summaries'])
        
        logger.info(f"Scraping completed: {total_products} total products, {total_reviews} total reviews")
        logger.info(f"Separate files saved in '{self.output_dir}' folder")
        
        return summary_data
    
    def _save_summary_report(self, summary_data: Dict[str, Any]):
        """Save a summary report of all keywords"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_filename = os.path.join(self.output_dir, f"scraping_summary_{timestamp}.json")
        
        try:
            with open(summary_filename, 'w', encoding='utf-8') as f:
                json.dump(summary_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Summary report saved: {summary_filename}")
        except Exception as e:
            logger.error(f"Error saving summary report: {e}")
    
    def cleanup(self):
        """Clean up resources"""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
            
            if hasattr(self._thread_local, 'driver') and self._thread_local.driver:
                self._thread_local.driver.quit()
                self._thread_local.driver = None
            
            if self.session:
                self.session.close()

            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

def main():
    """Main function with comprehensive configuration for large-scale scraping"""
    
    # ========================
    # CONFIGURATION VARIABLES
    # ========================
    
    # Keywords to search for
    KEYWORDS = [
        "eyeshadow",
        "eyeliner"
    ]
    
    # === SCRAPING SCALE CONFIGURATION ===

    # use less than this as there is chance of getting blocked by Nykaa
    MAX_PRODUCTS_PER_KEYWORD = 500
    MAX_REVIEWS_PER_PRODUCT = 300
    
    # === PERFORMANCE CONFIGURATION ===
    MAX_THREADS = 2  # Increase for faster processing (but watch rate limits)
    
    # === BROWSER CONFIGURATION ===
    HEADLESS = True
    DELAY_RANGE = (2, 5)  # Longer delays for large-scale to avoid detection
    
    # === REVIEW SCRAPING CONFIGURATION ===
    MAX_SCROLL_ATTEMPTS = 200  # High for thorough extraction
    MAX_CONSECUTIVE_NO_NEW = 15  # More patience for large-scale
    REVIEW_LOAD_WAIT_TIME = 10  # Longer wait for heavy pages
    
    # === CHECKPOINT CONFIGURATION ===
    ENABLE_CHECKPOINTS = True  # Essential for large-scale scraping
    SAVE_FREQUENCY = 25  # Save progress every 25 products
    
    # === OUTPUT CONFIGURATION ===
    OUTPUT_DIR = "scrapped-data"  # Directory for separate JSON files
    
    # ========================
    # THREADING OPTIMIZATION
    # ========================
    
    effective_threads = 1 if len(KEYWORDS) == 1 else min(MAX_THREADS, len(KEYWORDS))
    
    logger.info("=" * 60)
    logger.info("NYKAA SCRAPER - FIXED VERSION WITH LOAD MORE")
    logger.info("=" * 60)
    logger.info(f"Keywords: {len(KEYWORDS)} ({KEYWORDS})")
    logger.info(f"Threads: {effective_threads}")
    logger.info(f"Products per keyword: {MAX_PRODUCTS_PER_KEYWORD}")
    logger.info(f"Reviews per product: {MAX_REVIEWS_PER_PRODUCT}")
    logger.info(f"Checkpoints enabled: {ENABLE_CHECKPOINTS}")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info("=" * 60)
    
    # Initialize optimized scraper
    scraper = NykaaScraper(
        headless=HEADLESS,
        delay_range=DELAY_RANGE,
        max_threads=effective_threads,
        max_reviews_per_product=MAX_REVIEWS_PER_PRODUCT,
        max_scroll_attempts=MAX_SCROLL_ATTEMPTS,
        max_consecutive_no_new=MAX_CONSECUTIVE_NO_NEW,
        review_load_wait_time=REVIEW_LOAD_WAIT_TIME,
        enable_checkpoints=ENABLE_CHECKPOINTS,
        save_frequency=SAVE_FREQUENCY,
        output_dir=OUTPUT_DIR
    )
    
    try:
        start_time = datetime.now()
        logger.info(f"Starting scrape at {start_time}")
        
        # Run scraping
        summary = scraper.scrape_keywords(KEYWORDS, MAX_PRODUCTS_PER_KEYWORD)
        
        # Print summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        total_products = sum(s['total_products'] for s in summary['keyword_summaries'])
        total_reviews = sum(s['total_reviews'] for s in summary['keyword_summaries'])
        
        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETED SUCCESSFULLY!")
        logger.info("=" * 60)
        logger.info(f"Duration: {duration}")
        logger.info(f"Total products: {total_products}")
        logger.info(f"Total reviews: {total_reviews}")
        logger.info(f"Average reviews per product: {total_reviews / max(1, total_products):.1f}")
        logger.info(f"Files saved in: {OUTPUT_DIR}/")
        logger.info("=" * 60)
        
        # Print per-keyword summary
        logger.info("PER-KEYWORD SUMMARY:")
        for summary_item in summary['keyword_summaries']:
            logger.info(f"  {summary_item['keyword']}: {summary_item['total_products']} products, {summary_item['total_reviews']} reviews")
        
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user - progress saved in checkpoints")
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
    finally:
        scraper.cleanup()

if __name__ == "__main__":
    main() 