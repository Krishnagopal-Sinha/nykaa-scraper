#!/usr/bin/env python3
"""
Nykaa Product Scraper

A comprehensive web scraper for Nykaa.com that collects:
- Product information (name, price, ratings, images, descriptions, etc.)
- Product reviews/comments with detailed user information
- Seller/brand information
- Product variants and specifications

Usage:
    python nykaa_scraper.py

Author: AI Assistant
Date: 2024
"""

import requests
import json
import time
import random
import re
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse, parse_qs
from dataclasses import dataclass, asdict
from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
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


class NykaaScraper:
    """Main scraper class for Nykaa.com"""
    
    def __init__(self, headless: bool = True, delay_range: tuple = (1, 3), max_threads: int = 2):
        """
        Initialize the Nykaa scraper
        
        Args:
            headless: Whether to run browser in headless mode
            delay_range: Random delay range between requests (min, max) seconds
            max_threads: Maximum number of threads for parallel processing
        """
        self.base_url = "https://www.nykaa.com"
        self.delay_range = delay_range
        self.max_threads = max_threads
        self.ua = UserAgent()
        self.session = requests.Session()
        self.driver = None
        self.headless = headless
        
        # Thread safety
        self._data_lock = Lock()
        self._thread_local = threading.local()
        
        # Setup session headers
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        self.scraped_data = {
            'scrape_metadata': {
                'scrape_date': datetime.now().isoformat(),
                'total_products': 0,
                'total_reviews': 0,
                'keywords_searched': []
            },
            'products': []
        }
    
    def _get_thread_driver(self):
        """Get or create a driver instance for the current thread"""
        if not hasattr(self._thread_local, 'driver') or self._thread_local.driver is None:
            logger.info(f"Creating new driver for thread {threading.current_thread().name}")
            self._thread_local.driver = self._create_driver_instance()
        return self._thread_local.driver
    
    def _create_driver_instance(self):
        """Create a new WebDriver instance"""
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless")
            
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument(f"--user-agent={self.ua.random}")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Use a simpler, more reliable ChromeDriver setup
            service = self._get_chromedriver_service()
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            logger.info(f"WebDriver created for thread {threading.current_thread().name}")
            return driver
            
        except Exception as e:
            logger.error(f"Failed to create WebDriver for thread {threading.current_thread().name}: {e}")
            raise
    
    def _get_chromedriver_service(self):
        """Get ChromeDriver service with simplified setup"""
        # Check if we already have a working driver path stored
        if not hasattr(self, '_chromedriver_path'):
            self._chromedriver_path = self._setup_chromedriver()
        
        return Service(self._chromedriver_path)
    
    def _setup_chromedriver(self):
        """Setup ChromeDriver once and reuse"""
        import platform
        import subprocess
        import os
        import requests
        import zipfile
        import stat
        
        logger.info("Setting up ChromeDriver...")
        
        # Try system ChromeDriver first
        try:
            result = subprocess.run(['which', 'chromedriver'], capture_output=True, text=True)
            if result.returncode == 0:
                driver_path = result.stdout.strip()
                logger.info(f"Using system ChromeDriver: {driver_path}")
                return driver_path
        except Exception:
            pass
        
        # Try webdriver-manager as second option
        try:
            driver_path = ChromeDriverManager().install()
            logger.info(f"webdriver-manager returned path: {driver_path}")
            
            # Verify the path is actually executable
            if os.path.isfile(driver_path) and os.access(driver_path, os.X_OK):
                # Check if it's not the THIRD_PARTY_NOTICES file
                if not driver_path.endswith('THIRD_PARTY_NOTICES.chromedriver'):
                    logger.info(f"Using webdriver-manager ChromeDriver: {driver_path}")
                    return driver_path
            
            # If webdriver-manager returned wrong path, search for the actual executable
            logger.info("webdriver-manager returned wrong path, searching for actual chromedriver...")
            
            # Get the base cache directory from the returned path
            if '.wdm' in driver_path:
                # Extract the version directory
                # Path looks like: /Users/user/.wdm/drivers/chromedriver/mac64/138.0.7204.157/chromedriver-mac-arm64/THIRD_PARTY_NOTICES.chromedriver
                path_parts = driver_path.split('/')
                version_dir = None
                for i, part in enumerate(path_parts):
                    if part.startswith('chromedriver-'):  # Find chromedriver-mac-arm64 directory
                        version_dir = '/'.join(path_parts[:i+1])
                        break
                
                if version_dir and os.path.exists(version_dir):
                    logger.info(f"Searching in version directory: {version_dir}")
                    
                    # Look for chromedriver executable in this directory
                    for file in os.listdir(version_dir):
                        if file == 'chromedriver':
                            potential_path = os.path.join(version_dir, file)
                            if os.path.isfile(potential_path):
                                # Make sure it has execute permissions
                                os.chmod(potential_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                                
                                if os.access(potential_path, os.X_OK):
                                    # Test if it actually works
                                    try:
                                        test_result = subprocess.run([potential_path, '--version'], 
                                                                   capture_output=True, text=True, timeout=5)
                                        if test_result.returncode == 0:
                                            logger.info(f"Found working ChromeDriver: {potential_path}")
                                            return potential_path
                                    except Exception as e:
                                        logger.warning(f"Test failed for {potential_path}: {e}")
                                        continue
                
                # Fallback: search the entire cache directory structure
                cache_base = os.path.expanduser("~/.wdm")
                if os.path.exists(cache_base):
                    logger.info(f"Searching entire cache directory: {cache_base}")
                    for root, dirs, files in os.walk(cache_base):
                        for file in files:
                            if file == 'chromedriver':
                                potential_path = os.path.join(root, file)
                                if os.path.isfile(potential_path):
                                    # Skip THIRD_PARTY_NOTICES files
                                    if 'THIRD_PARTY_NOTICES' in potential_path:
                                        continue
                                    
                                    # Make sure it has execute permissions
                                    try:
                                        os.chmod(potential_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                                    except Exception:
                                        pass
                                    
                                    if os.access(potential_path, os.X_OK):
                                        # Test if it actually works
                                        try:
                                            test_result = subprocess.run([potential_path, '--version'], 
                                                                       capture_output=True, text=True, timeout=5)
                                            if test_result.returncode == 0:
                                                logger.info(f"Found working ChromeDriver in cache: {potential_path}")
                                                return potential_path
                                        except Exception as e:
                                            logger.debug(f"Test failed for {potential_path}: {e}")
                                            continue
                                
        except Exception as e:
            logger.warning(f"webdriver-manager failed: {e}")
        
        # Download and setup ChromeDriver manually
        logger.info("Downloading ChromeDriver manually...")
        
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
        
        # Try to get Chrome version
        chrome_version = self._get_chrome_version()
        
        # List of versions to try (latest stable versions)
        versions_to_try = []
        if chrome_version:
            versions_to_try.append(chrome_version)
        
        # Add some recent stable versions as fallbacks
        stable_versions = [
            "131.0.6778.85",
            "131.0.6778.69", 
            "130.0.6723.116",
            "130.0.6723.91",
            "129.0.6668.100"
        ]
        versions_to_try.extend(stable_versions)
        
        # Try each version until one works
        for version in versions_to_try:
            try:
                download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform_name}/chromedriver-{platform_name}.zip"
                
                logger.info(f"Trying ChromeDriver version {version}...")
                
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
        
        raise Exception("Could not download or setup ChromeDriver")
    
    def _get_chrome_version(self):
        """Get installed Chrome version"""
        try:
            import subprocess
            
            # Try different Chrome executable paths
            chrome_paths = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "google-chrome-stable",
                "google-chrome",
                "chromium-browser"
            ]
            
            for chrome_path in chrome_paths:
                try:
                    result = subprocess.run([chrome_path, "--version"], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        version_text = result.stdout.strip()
                        # Extract version number
                        import re
                        version_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', version_text)
                        if version_match:
                            version = version_match.group(1)
                            logger.info(f"Detected Chrome version: {version}")
                            return version
                except Exception:
                    continue
            
            logger.warning("Could not detect Chrome version")
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting Chrome version: {e}")
            return None
    
    def setup_driver(self):
        """Setup Selenium WebDriver with proper configuration"""
        try:
            self.driver = self._create_driver_instance()
            logger.info("Main WebDriver setup completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to setup main WebDriver: {e}")
            raise
    
    def random_delay(self):
        """Add random delay between requests to avoid rate limiting"""
        delay = random.uniform(*self.delay_range)
        time.sleep(delay)
    
    def _try_webdriver_manager(self):
        """Try to setup driver using webdriver-manager"""
        try:
            # Clear any corrupted cache first
            import os
            import shutil
            cache_dir = os.path.expanduser("~/.wdm")
            if os.path.exists(cache_dir):
                logger.info("Clearing webdriver-manager cache...")
                shutil.rmtree(cache_dir)
            
            driver_path = ChromeDriverManager().install()
            logger.info(f"webdriver-manager returned path: {driver_path}")
            
            # The webdriver-manager sometimes returns the wrong file path
            # We need to find the actual chromedriver executable
            actual_driver_path = None
            
            # First check if the returned path is actually executable
            if os.path.isfile(driver_path) and os.access(driver_path, os.X_OK):
                # Check if it's not the THIRD_PARTY_NOTICES file
                if not driver_path.endswith('THIRD_PARTY_NOTICES.chromedriver'):
                    actual_driver_path = driver_path
            
            # If not found, search in the directory tree
            if not actual_driver_path:
                search_dir = os.path.dirname(driver_path)
                # Go up a few levels to find the base download directory
                for _ in range(3):
                    search_dir = os.path.dirname(search_dir)
                    if os.path.basename(search_dir) == '.wdm':
                        break
                
                logger.info(f"Searching for chromedriver executable in: {search_dir}")
                
                # Search for the actual chromedriver executable
                for root, dirs, files in os.walk(search_dir):
                    for file in files:
                        if file == 'chromedriver' and not file.endswith('.chromedriver'):
                            potential_path = os.path.join(root, file)
                            if os.path.isfile(potential_path) and os.access(potential_path, os.X_OK):
                                # Double check it's not a text file by trying to read the first few bytes
                                try:
                                    with open(potential_path, 'rb') as f:
                                        header = f.read(4)
                                        # Executable files typically start with specific magic bytes
                                        # On macOS, look for Mach-O magic bytes or ELF
                                        if header.startswith(b'\xcf\xfa\xed\xfe') or header.startswith(b'\xfe\xed\xfa'):  # Mach-O 64-bit
                                            actual_driver_path = potential_path
                                            break
                                        elif header.startswith(b'\x7fELF'):  # ELF format
                                            actual_driver_path = potential_path
                                            break
                                except:
                                    continue
                    if actual_driver_path:
                        break
            
            if not actual_driver_path:
                raise Exception(f"Could not find executable chromedriver in downloaded package. Searched from: {driver_path}")
            
            logger.info(f"Using ChromeDriver from webdriver-manager: {actual_driver_path}")
            return Service(actual_driver_path)
            
        except Exception as e:
            logger.warning(f"webdriver-manager failed: {e}")
            raise
    
    def _try_system_chromedriver(self):
        """Try to use system-installed ChromeDriver"""
        try:
            import subprocess
            result = subprocess.run(['which', 'chromedriver'], capture_output=True, text=True)
            if result.returncode == 0:
                driver_path = result.stdout.strip()
                logger.info(f"Using system ChromeDriver: {driver_path}")
                return Service(driver_path)
            else:
                raise Exception("System ChromeDriver not found")
        except Exception as e:
            logger.warning(f"System ChromeDriver not available: {e}")
            raise
    
    def _try_manual_chromedriver_install(self):
        """Try to download and install ChromeDriver manually"""
        try:
            import subprocess
            import zipfile
            import platform
            import requests
            import os
            
            # Get Chrome version with multiple detection methods
            chrome_version = None
            major_version = "131"  # Default fallback
            
            detection_methods = [
                # macOS methods
                lambda: subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"], 
                                     capture_output=True, text=True, timeout=10),
                # Alternative macOS method
                lambda: subprocess.run(["google-chrome", "--version"], 
                                     capture_output=True, text=True, timeout=10),
                # Linux method
                lambda: subprocess.run(["google-chrome-stable", "--version"], 
                                     capture_output=True, text=True, timeout=10),
                # Check Chrome application directory (macOS)
                lambda: subprocess.run(["defaults", "read", "/Applications/Google Chrome.app/Contents/Info", "CFBundleShortVersionString"], 
                                     capture_output=True, text=True, timeout=10)
            ]
            
            for method in detection_methods:
                try:
                    result = method()
                    if result.returncode == 0 and result.stdout.strip():
                        version_text = result.stdout.strip()
                        # Extract version number from various formats
                        import re
                        version_match = re.search(r'(\d+)\.(\d+)\.(\d+)\.(\d+)', version_text)
                        if version_match:
                            chrome_version = version_match.group(0)
                            major_version = version_match.group(1)
                            logger.info(f"Detected Chrome version: {chrome_version}")
                            break
                except Exception as e:
                    logger.debug(f"Chrome detection method failed: {e}")
                    continue
            
            if not chrome_version:
                logger.warning(f"Could not detect Chrome version, using default major version: {major_version}")
            
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
            
            # Create a local drivers directory
            drivers_dir = os.path.join(os.getcwd(), "drivers")
            os.makedirs(drivers_dir, exist_ok=True)
            
            # Try to find a compatible ChromeDriver version
            base_url = "https://storage.googleapis.com/chrome-for-testing-public"
            download_url = None
            
            # Try exact version first, then nearby versions
            version_attempts = []
            if chrome_version:
                version_attempts.append(chrome_version)
            
            # Add some common stable versions for the major version
            major_int = int(major_version)
            for minor_offset in [0, 1, 2, 3, 4, 5]:
                for patch_offset in [0, 1, 2, 3]:
                    test_version = f"{major_int}.0.{6112 + minor_offset}.{105 + patch_offset}"
                    if test_version not in version_attempts:
                        version_attempts.append(test_version)
            
            # Also try some versions from adjacent major versions
            for major_offset in [-1, 1, -2, 2]:
                test_major = major_int + major_offset
                if test_major >= 114:  # Minimum supported version
                    version_attempts.append(f"{test_major}.0.6112.105")
            
            for test_version in version_attempts:
                try:
                    test_url = f"{base_url}/{test_version}/{platform_name}/chromedriver-{platform_name}.zip"
                    logger.info(f"Trying ChromeDriver version: {test_version}")
                    
                    # Quick HEAD request to check if URL exists
                    head_response = requests.head(test_url, timeout=10)
                    if head_response.status_code == 200:
                        download_url = test_url
                        logger.info(f"Found compatible ChromeDriver version: {test_version}")
                        break
                except Exception as e:
                    logger.debug(f"Version {test_version} not available: {e}")
                    continue
            
            if not download_url:
                raise Exception(f"Could not find compatible ChromeDriver for Chrome {chrome_version} on {platform_name}")
            
            # Download ChromeDriver
            logger.info(f"Downloading ChromeDriver from: {download_url}")
            response = requests.get(download_url, timeout=120)
            response.raise_for_status()
            
            # Save and extract
            zip_path = os.path.join(drivers_dir, "chromedriver.zip")
            with open(zip_path, "wb") as f:
                f.write(response.content)
            
            # Extract
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(drivers_dir)
            
            # Find the chromedriver executable
            driver_path = None
            for root, dirs, files in os.walk(drivers_dir):
                for file in files:
                    if file == 'chromedriver':
                        potential_path = os.path.join(root, file)
                        # Verify it's actually an executable file
                        if os.path.isfile(potential_path):
                            try:
                                # Check file header to ensure it's a binary executable
                                with open(potential_path, 'rb') as f:
                                    header = f.read(4)
                                    if (header.startswith(b'\xcf\xfa\xed\xfe') or  # Mach-O 64-bit
                                        header.startswith(b'\xfe\xed\xfa') or      # Mach-O
                                        header.startswith(b'\x7fELF')):            # ELF
                                        driver_path = potential_path
                                        break
                            except:
                                continue
                if driver_path:
                    break
            
            if not driver_path:
                raise Exception("Could not find chromedriver executable after extraction")
            
            # Make sure it's executable on Unix systems
            os.chmod(driver_path, 0o755)
            
            # Clean up zip file
            try:
                os.remove(zip_path)
            except:
                pass
            
            logger.info(f"Successfully downloaded and installed ChromeDriver: {driver_path}")
            return Service(driver_path)
            
        except Exception as e:
            logger.error(f"Manual ChromeDriver installation failed: {e}")
            raise
    
    def _scrape_keyword_thread(self, keyword: str, max_products: int) -> List[Dict[str, Any]]:
        """
        Thread worker function to scrape products for a single keyword
        
        Args:
            keyword: Search keyword
            max_products: Maximum number of products to scrape for this keyword
            
        Returns:
            List of scraped product data dictionaries
        """
        thread_name = threading.current_thread().name
        logger.info(f"[{thread_name}] Starting to scrape keyword: '{keyword}'")
        
        try:
            # Get thread-local driver
            driver = self._get_thread_driver()
            
            # Search for products
            product_urls = self._search_products_with_driver(driver, keyword, max_products)
            logger.info(f"[{thread_name}] Found {len(product_urls)} URLs for keyword '{keyword}'")
            
            # Scrape each product
            scraped_products = []
            for i, url in enumerate(product_urls, 1):
                try:
                    logger.info(f"[{thread_name}] Scraping product {i}/{len(product_urls)} for '{keyword}': {url}")
                    product_info = self._scrape_product_details_with_driver(driver, url)
                    if product_info:
                        scraped_products.append(asdict(product_info))
                    
                    self.random_delay()
                    
                except Exception as e:
                    logger.error(f"[{thread_name}] Error scraping product {url}: {e}")
                    continue
            
            logger.info(f"[{thread_name}] Completed scraping for keyword '{keyword}': {len(scraped_products)} products")
            return scraped_products
            
        except Exception as e:
            logger.error(f"[{thread_name}] Error scraping keyword '{keyword}': {e}")
            return []
    
    def _search_products_with_driver(self, driver, keyword: str, max_products: int = 50) -> List[str]:
        """
        Search for products using keyword with specific driver instance
        
        Args:
            driver: WebDriver instance to use
            keyword: Search keyword
            max_products: Maximum number of products to scrape
            
        Returns:
            List of product URLs
        """
        logger.info(f"Searching for products with keyword: '{keyword}'")
        
        product_urls = []
        
        try:
            # Navigate to search page
            search_url = f"{self.base_url}/search/result/?q={keyword.replace(' ', '%20')}"
            driver.get(search_url)
            self.random_delay()
            
            # Handle any popups or overlays
            self._handle_popups_with_driver(driver)
            
            page_num = 1
            
            while len(product_urls) < max_products:
                logger.info(f"Scraping page {page_num} for keyword '{keyword}'")
                
                # Wait for product listings to load with multiple possible selectors
                try:
                    # Try different selectors that might indicate products are loaded
                    selectors_to_wait = [
                        ".productWrapper",
                        ".css-17nge1h", 
                        ".css-qlopj4",
                        "a[href*='/p/']"
                    ]
                    
                    element_found = False
                    for selector in selectors_to_wait:
                        try:
                            WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            element_found = True
                            break
                        except TimeoutException:
                            continue
                    
                    if not element_found:
                        logger.warning(f"No products found on page {page_num}")
                        break
                        
                except TimeoutException:
                    logger.warning(f"No products found on page {page_num}")
                    break
                
                # Extract product URLs from current page using the correct selectors
                product_link_selectors = [
                    ".css-qlopj4",  # Main product link class
                    "a[href*='/p/']",  # Any link containing /p/
                    ".productWrapper a",  # Links within product wrappers
                    ".css-17nge1h a"  # Links within product containers
                ]
                
                found_links = False
                for selector in product_link_selectors:
                    try:
                        product_cards = driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        if product_cards:
                            logger.info(f"Found {len(product_cards)} product links using selector: {selector}")
                            found_links = True
                            
                            for card in product_cards:
                                if len(product_urls) >= max_products:
                                    break
                                
                                try:
                                    product_url = card.get_attribute('href')
                                    if product_url and '/p/' in product_url and product_url not in product_urls:
                                        # Clean the URL - remove query parameters except productId
                                        if '?' in product_url:
                                            base_url_part = product_url.split('?')[0]
                                            # Keep only the base URL for consistency
                                            product_urls.append(base_url_part)
                                        else:
                                            product_urls.append(product_url)
                                except Exception as e:
                                    logger.warning(f"Error extracting product URL: {e}")
                                    continue
                            break  # Exit selector loop if we found products
                    except Exception as e:
                        logger.warning(f"Error with selector {selector}: {e}")
                        continue
                
                if not found_links:
                    logger.warning(f"No product links found on page {page_num} with any selector")
                    break
                
                # Try to go to next page
                try:
                    next_button_selectors = [
                        "[aria-label='Next']",
                        ".css-1zi560",  # Next button class from the analysis
                        "button:contains('Next')",
                        ".pagination-next",
                        ".next-page"
                    ]
                    
                    next_clicked = False
                    for selector in next_button_selectors:
                        try:
                            next_button = driver.find_element(By.CSS_SELECTOR, selector)
                            if next_button.is_enabled() and next_button.is_displayed():
                                driver.execute_script("arguments[0].click();", next_button)
                                self.random_delay()
                                page_num += 1
                                next_clicked = True
                                break
                        except NoSuchElementException:
                            continue
                    
                    if not next_clicked:
                        logger.info("No next page button found or reached last page")
                        break
                        
                except Exception as e:
                    logger.info(f"Pagination ended: {e}")
                    break
        
        except Exception as e:
            logger.error(f"Error during product search: {e}")
        
        logger.info(f"Found {len(product_urls)} product URLs for keyword '{keyword}'")
        return product_urls[:max_products]
    
    def search_products(self, keyword: str, max_products: int = 50) -> List[str]:
        """
        Search for products using keyword and return product URLs
        
        Args:
            keyword: Search keyword
            max_products: Maximum number of products to scrape
            
        Returns:
            List of product URLs
        """
        if not self.driver:
            self.setup_driver()
        
        return self._search_products_with_driver(self.driver, keyword, max_products)
    
    def _handle_popups_with_driver(self, driver):
        """Handle common popups and overlays on Nykaa including sign-in modals with specific driver"""
        try:
            # Wait a moment for popups to appear
            time.sleep(2)
            
            # List of common popup close methods
            close_methods = [
                # Close buttons by aria-label
                (By.CSS_SELECTOR, "[aria-label='Close']"),
                (By.CSS_SELECTOR, "[aria-label='close']"),
                (By.CSS_SELECTOR, "[aria-label='Close modal']"),
                (By.CSS_SELECTOR, "[aria-label='Close dialog']"),
                
                # Close buttons by common text
                (By.XPATH, "//button[contains(text(), 'Close')]"),
                (By.XPATH, "//button[contains(text(), '×')]"),
                (By.XPATH, "//span[contains(text(), '×')]"),
                (By.XPATH, "//div[contains(text(), '×')]"),
                
                # Skip/Dismiss buttons for sign-in popups
                (By.XPATH, "//button[contains(text(), 'Skip')]"),
                (By.XPATH, "//button[contains(text(), 'Not now')]"),
                (By.XPATH, "//button[contains(text(), 'Maybe later')]"),
                (By.XPATH, "//button[contains(text(), 'Continue without signing in')]"),
                (By.XPATH, "//a[contains(text(), 'Skip')]"),
                
                # Generic close selectors
                (By.CSS_SELECTOR, ".close"),
                (By.CSS_SELECTOR, ".close-btn"),
                (By.CSS_SELECTOR, ".modal-close"),
                (By.CSS_SELECTOR, ".popup-close"),
                
                # Click outside modal (overlay areas)
                (By.CSS_SELECTOR, ".modal-overlay"),
                (By.CSS_SELECTOR, ".overlay"),
                (By.CSS_SELECTOR, "[class*='overlay']"),
            ]
            
            for method, selector in close_methods:
                try:
                    if method == By.CSS_SELECTOR:
                        elements = driver.find_elements(method, selector)
                    else:  # XPATH
                        elements = driver.find_elements(method, selector)
                    
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            try:
                                # Try clicking the element
                                driver.execute_script("arguments[0].click();", element)
                                time.sleep(1)
                                logger.info(f"Successfully closed popup using: {selector}")
                                break
                            except Exception as e:
                                logger.debug(f"Failed to click close element: {e}")
                                continue
                    else:
                        continue
                    break  # If we successfully closed something, exit the outer loop
                        
                except Exception as e:
                    logger.debug(f"Error with popup close method {selector}: {e}")
                    continue
            
            # Try pressing Escape key as last resort
            try:
                from selenium.webdriver.common.keys import Keys
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(1)
                logger.debug("Tried pressing Escape key")
            except Exception:
                pass
                
        except Exception as e:
            logger.debug(f"Error in popup handling: {e}")

    def _handle_popups(self):
        """Handle common popups and overlays on Nykaa including sign-in modals"""
        self._handle_popups_with_driver(self.driver)

    def _scrape_product_details_with_driver(self, driver, product_url: str) -> Optional[ProductInfo]:
        """
        Scrape comprehensive product details from product page using specific driver
        
        Args:
            driver: WebDriver instance to use
            product_url: URL of the product page
            
        Returns:
            ProductInfo object with all scraped data
        """
        logger.info(f"Scraping product: {product_url}")
        
        try:
            driver.get(product_url)
            self.random_delay()
            
            # Handle popups
            self._handle_popups_with_driver(driver)
            
            # Wait for page to load
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h1, .product-title"))
            )
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract basic product information
            product_info = self._extract_basic_product_info(soup, product_url)
            
            if not product_info:
                logger.warning(f"Could not extract basic product info from {product_url}")
                return None
            
            # Extract detailed information
            product_info.description = self._extract_description(soup)
            product_info.key_features = self._extract_key_features(soup)
            product_info.ingredients = self._extract_ingredients(soup)
            product_info.how_to_use = self._extract_how_to_use(soup)
            product_info.images = self._extract_images(soup)
            product_info.variants = self._extract_variants(soup)
            product_info.specifications = self._extract_specifications(soup)
            product_info.tags = self._extract_tags(soup)
            product_info.availability = self._extract_availability(soup)
            product_info.delivery_info = self._extract_delivery_info(soup)
            product_info.return_policy = self._extract_return_policy(soup)
            product_info.seller_info = self._extract_seller_info(soup)
            
            # Extract reviews (this might require scrolling or pagination)
            product_info.reviews = self._extract_reviews_with_driver(driver, product_url)
            
            product_info.scraped_at = datetime.now().isoformat()
            
            logger.info(f"Successfully scraped product: {product_info.name}")
            return product_info
            
        except Exception as e:
            logger.error(f"Error scraping product {product_url}: {e}")
            return None

    def scrape_product_details(self, product_url: str) -> Optional[ProductInfo]:
        """
        Scrape comprehensive product details from product page
        
        Args:
            product_url: URL of the product page
            
        Returns:
            ProductInfo object with all scraped data
        """
        if not self.driver:
            self.setup_driver()
        
        return self._scrape_product_details_with_driver(self.driver, product_url)
    
    def _extract_basic_product_info(self, soup: BeautifulSoup, product_url: str) -> Optional[ProductInfo]:
        """Extract basic product information from JSON data embedded in the page"""
        try:
            # Look for the main product data in script tags
            product_data = None
            
            # Find the script tag with window.__PRELOADED_STATE__
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'window.__PRELOADED_STATE__' in script.string:
                    script_content = script.string
                    # Extract JSON from the script using improved boundary detection
                    try:
                        product_data = self._extract_json_data_safely(script_content, 'window.__PRELOADED_STATE__ = ')
                        if product_data and isinstance(product_data, dict):
                            # Navigate to the product details
                            product_details = product_data.get('productPage', {}).get('productDetails', {})
                            if product_details and product_details.get('name'):
                                product_data = product_details
                                break
                    except Exception as e:
                        logger.warning(f"Failed to parse JSON from script tag: {e}")
                        continue
            
            # If product data found in JSON, extract from there
            if product_data and product_data.get('name'):
                return self._extract_from_json_data(product_data, product_url)
            
            # Fallback: try to extract from HTML elements (if JSON extraction fails)
            logger.warning("JSON extraction failed, trying HTML extraction as fallback")
            return self._extract_from_html_fallback(soup, product_url)
            
        except Exception as e:
            logger.error(f"Error extracting basic product info: {e}")
            return None

    def _extract_json_data_safely(self, script_content: str, start_marker: str) -> dict:
        """Safely extract JSON data from script content"""
        try:
            start = script_content.find(start_marker)
            if start == -1:
                return {}
            
            start += len(start_marker)
            
            # Find the end of the JSON by looking for the next script or window statement
            possible_ends = [
                script_content.find('window.__APP_DATA__', start),
                script_content.find('window.dataLayer', start),
                script_content.find('</script>', start),
                script_content.find('window.', start + 100),  # Look for next window statement
                script_content.find('\n<script', start),
                script_content.find('\nwindow.', start + 100)
            ]
            
            # Use the earliest valid end position
            valid_ends = [end for end in possible_ends if end > start]
            if valid_ends:
                end = min(valid_ends)
            else:
                end = len(script_content) - 10
            
            # Extract the potential JSON string
            json_str = script_content[start:end].strip()
            
            # Clean up the JSON string
            json_str = json_str.rstrip(';').strip()
            
            # Try to find the end of the JSON object by counting braces
            if json_str.startswith('{'):
                brace_count = 0
                actual_end = 0
                in_string = False
                escape_next = False
                
                for i, char in enumerate(json_str):
                    if escape_next:
                        escape_next = False
                        continue
                    
                    if char == '\\':
                        escape_next = True
                        continue
                    
                    if char == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    
                    if not in_string:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                actual_end = i + 1
                                break
                
                if actual_end > 0:
                    json_str = json_str[:actual_end]
            
            return json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Error extracting JSON safely: {e}")
            return {}

    def _extract_from_json_data(self, product_data: dict, product_url: str) -> ProductInfo:
        """Extract product information from JSON data"""
        try:
            # Basic information
            name = product_data.get('name', 'Unknown Product')
            brand = product_data.get('brandName', 'Unknown Brand')
            
            # Category information
            category_levels = product_data.get('categoryLevels', {})
            primary_categories = product_data.get('primaryCategories', {})
            
            category = "Unknown"
            subcategory = "Unknown"
            
            if primary_categories:
                l1 = primary_categories.get('l1', {})
                l2 = primary_categories.get('l2', {})
                l3 = primary_categories.get('l3', {})
                
                category = l2.get('name', l1.get('name', 'Unknown'))
                subcategory = l3.get('name', l2.get('name', 'Unknown'))
            
            # Pricing
            price = float(product_data.get('mrp', 0))
            discounted_price = product_data.get('offerPrice')
            if discounted_price:
                discounted_price = float(discounted_price)
            
            # Calculate discount percentage
            discount_percentage = None
            if discounted_price and price and price > 0:
                discount_percentage = round(((price - discounted_price) / price) * 100, 2)
            elif product_data.get('discount'):
                discount_percentage = float(product_data.get('discount', 0))
            
            # Rating and reviews
            rating = float(product_data.get('rating', 0))
            review_count = int(product_data.get('reviewCount', 0))
            rating_count = int(product_data.get('ratingCount', 0))
            
            # Product ID
            product_id = str(product_data.get('parentId', product_data.get('id', self._extract_product_id(product_url))))
            
            # Extract more detailed information
            description = product_data.get('description', '')
            if not description:
                # Try to get description from other fields
                ingredients_text = product_data.get('ingredients', '')
                if ingredients_text and isinstance(ingredients_text, str):
                    # Clean HTML from ingredients text
                    description = self._clean_html_text(ingredients_text)
            
            # Key features (extract from description or other fields)
            key_features = []
            if description:
                # Try to extract features from description
                feature_patterns = [
                    r'<b>Key Features:</b>\s*(.+?)(?:<b>|$)',
                    r'Features:\s*(.+?)(?:\n|$)',
                ]
                for pattern in feature_patterns:
                    match = re.search(pattern, description, re.IGNORECASE | re.DOTALL)
                    if match:
                        features_text = match.group(1)
                        # Split by common delimiters
                        features = [f.strip() for f in re.split(r'[•\n\r-]', features_text) if f.strip()]
                        key_features = features[:5]  # Limit to first 5 features
                        break
            
            # Ingredients
            ingredients = []
            ingredients_text = product_data.get('ingredients', '')
            if ingredients_text:
                ingredients = self._extract_ingredients_from_text(ingredients_text)
            
            # How to use
            how_to_use = product_data.get('howToUse', '')
            if how_to_use:
                how_to_use = self._clean_html_text(how_to_use)
            
            # Images
            images = []
            if product_data.get('imageUrl'):
                images.append(product_data['imageUrl'])
            
            # Add images from media array
            media = product_data.get('media', [])
            if isinstance(media, list):
                for media_item in media:
                    if isinstance(media_item, dict) and media_item.get('url'):
                        images.append(media_item['url'])
            
            # Add images from carousel
            carousel = product_data.get('carousel', [])
            if isinstance(carousel, list):
                for carousel_item in carousel:
                    if isinstance(carousel_item, dict) and carousel_item.get('url'):
                        images.append(carousel_item['url'])
            
            # Remove duplicates from images
            images = list(dict.fromkeys(images))
            
            # Variants
            variants = self._extract_variants_from_json(product_data)
            
            # Specifications
            specifications = {}
            if product_data.get('packSize'):
                specifications['Pack Size'] = product_data['packSize']
            if product_data.get('expiry'):
                specifications['Expiry'] = product_data['expiry']
            if product_data.get('sku'):
                specifications['SKU'] = product_data['sku']
            
            # Manufacture details
            manufacture = product_data.get('manufacture', [])
            if manufacture and isinstance(manufacture, list) and len(manufacture) > 0:
                mfg_info = manufacture[0]
                if isinstance(mfg_info, dict):
                    specifications.update({
                        'Manufacturer': mfg_info.get('manufacturerName', ''),
                        'Country of Origin': mfg_info.get('originOfCountryName', ''),
                        'Importer': mfg_info.get('importerName', '')
                    })
            
            # Tags
            tags = product_data.get('tags', [])
            if not isinstance(tags, list):
                tags = []
            
            # Availability
            availability = "In Stock" if product_data.get('inStock', False) else "Out of Stock"
            
            # Delivery and return info
            delivery_info = ""
            return_policy = product_data.get('returnMessage', product_data.get('messageOnReturn', ''))
            
            # Seller info
            seller_info = SellerInfo(
                seller_name=product_data.get('sellerName', 'Nykaa'),
                seller_id=None,
                brand_name=brand,
                brand_id=None,
                seller_rating=None,
                seller_reviews_count=None,
                brand_description=None,
                official_store=True
            )
            
            return ProductInfo(
                product_id=product_id,
                name=name,
                brand=brand,
                category=category,
                subcategory=subcategory,
                price=price,
                discounted_price=discounted_price,
                discount_percentage=discount_percentage,
                rating=rating,
                review_count=review_count,
                description=description,
                key_features=key_features,
                ingredients=ingredients,
                how_to_use=how_to_use,
                images=images,
                variants=variants,
                seller_info=seller_info,
                reviews=[],  # Will be populated by _extract_reviews
                specifications=specifications,
                tags=tags,
                availability=availability,
                delivery_info=delivery_info,
                return_policy=return_policy,
                scraped_at="",
                product_url=product_url
            )
            
        except Exception as e:
            logger.error(f"Error extracting from JSON data: {e}")
            # Fallback to HTML extraction
            return self._extract_from_html_fallback(None, product_url)

    def _extract_from_html_fallback(self, soup: BeautifulSoup, product_url: str) -> Optional[ProductInfo]:
        """Fallback method to extract from HTML when JSON extraction fails"""
        try:
            if not soup:
                return None
                
            # Product name
            name_selectors = ['h1', '.product-title', '[data-testid="product-title"]']
            name = self._get_text_by_selectors(soup, name_selectors, "Unknown Product")
            
            # Brand - try to extract from JSON in script tags first
            brand = "Unknown Brand"
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and '"brandName"' in script.string:
                    try:
                        brand_match = re.search(r'"brandName":"([^"]+)"', script.string)
                        if brand_match:
                            brand = brand_match.group(1)
                            break
                    except:
                        continue
            
            if brand == "Unknown Brand":
                brand_selectors = ['.brand-name', '[data-testid="brand-name"]', '.brand']
                brand = self._get_text_by_selectors(soup, brand_selectors, "Unknown Brand")
            
            # Category and subcategory
            breadcrumb = soup.find('nav', {'aria-label': 'breadcrumb'}) or soup.find('.breadcrumb')
            category = subcategory = "Unknown"
            
            if breadcrumb:
                crumbs = breadcrumb.find_all('a')
                if len(crumbs) >= 2:
                    category = crumbs[1].get_text(strip=True)
                if len(crumbs) >= 3:
                    subcategory = crumbs[2].get_text(strip=True)
            
            # Price information - try JSON first
            price = 0
            discounted_price = None
            
            for script in script_tags:
                if script.string and '"mrp"' in script.string:
                    try:
                        mrp_match = re.search(r'"mrp":(\d+)', script.string)
                        offer_match = re.search(r'"offerPrice":(\d+)', script.string)
                        if mrp_match:
                            price = float(mrp_match.group(1))
                        if offer_match:
                            discounted_price = float(offer_match.group(1))
                        if price > 0:
                            break
                    except:
                        continue
            
            if price == 0:
                price_selectors = ['.price', '[data-testid="price"]', '.product-price']
                price_text = self._get_text_by_selectors(soup, price_selectors, "0")
                price = self._extract_price(price_text)
                
                discounted_price_selectors = ['.discounted-price', '.sale-price', '.offer-price']
                discounted_price_text = self._get_text_by_selectors(soup, discounted_price_selectors)
                discounted_price = self._extract_price(discounted_price_text) if discounted_price_text else None
            
            # Calculate discount percentage
            discount_percentage = None
            if discounted_price and price and price > 0:
                discount_percentage = round(((price - discounted_price) / price) * 100, 2)
            
            # Rating and review count - try JSON first
            rating = 0
            review_count = 0
            
            for script in script_tags:
                if script.string and '"rating"' in script.string:
                    try:
                        rating_match = re.search(r'"rating":([0-9.]+)', script.string)
                        review_match = re.search(r'"reviewCount":"?(\d+)"?', script.string)
                        if rating_match:
                            rating = float(rating_match.group(1))
                        if review_match:
                            review_count = int(review_match.group(1))
                        if rating > 0:
                            break
                    except:
                        continue
            
            if rating == 0:
                rating_selectors = ['.rating', '[data-testid="rating"]', '.star-rating']
                rating_text = self._get_text_by_selectors(soup, rating_selectors, "0")
                rating = self._extract_rating(rating_text)
                
                review_count_selectors = ['.review-count', '[data-testid="review-count"]', '.reviews-count']
                review_count_text = self._get_text_by_selectors(soup, review_count_selectors, "0")
                review_count = self._extract_number(review_count_text)
            
            # Extract product ID from URL
            product_id = self._extract_product_id(product_url)
            
            return ProductInfo(
                product_id=product_id,
                name=name,
                brand=brand,
                category=category,
                subcategory=subcategory,
                price=price,
                discounted_price=discounted_price,
                discount_percentage=discount_percentage,
                rating=rating,
                review_count=review_count,
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
            
        except Exception as e:
            logger.error(f"Error in HTML fallback extraction: {e}")
            return None

    def _clean_html_text(self, html_text: str) -> str:
        """Clean HTML tags and entities from text"""
        if not html_text:
            return ""
        
        # Remove HTML tags
        import re
        text = re.sub(r'<[^>]+>', '', html_text)
        
        # Decode HTML entities
        import html
        text = html.unescape(text)
        
        # Clean up whitespace
        text = ' '.join(text.split())
        
        return text.strip()

    def _extract_ingredients_from_text(self, ingredients_text: str) -> List[str]:
        """Extract ingredients list from text"""
        if not ingredients_text:
            return []
        
        # Clean HTML
        clean_text = self._clean_html_text(ingredients_text)
        
        # Look for ingredients section
        ingredients_match = re.search(r'Ingredients[:\s]*(.+)', clean_text, re.IGNORECASE | re.DOTALL)
        if ingredients_match:
            ingredients_part = ingredients_match.group(1)
        else:
            ingredients_part = clean_text
        
        # Split by common delimiters
        ingredients = []
        for delimiter in [',', ';', '\n']:
            if delimiter in ingredients_part:
                ingredients = [ing.strip() for ing in ingredients_part.split(delimiter) if ing.strip()]
                break
        
        # If no delimiters found, return as single ingredient
        if not ingredients and ingredients_part.strip():
            ingredients = [ingredients_part.strip()]
        
        return ingredients[:20]  # Limit to 20 ingredients

    def _extract_variants_from_json(self, product_data: dict) -> List[ProductVariant]:
        """Extract product variants from JSON data"""
        variants = []
        
        try:
            # Check for variant data in children
            children = product_data.get('children', [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        variant_name = child.get('variantName', child.get('name', ''))
                        if variant_name:
                            variants.append(ProductVariant(
                                name=variant_name,
                                price=child.get('mrp'),
                                discounted_price=child.get('offerPrice'),
                                availability="In Stock" if child.get('inStock', False) else "Out of Stock",
                                variant_id=str(child.get('childId', child.get('id', '')))
                            ))
            
            # Check for selected variant
            selected_variant = product_data.get('selectedVariantName')
            if selected_variant and not any(v.name == selected_variant for v in variants):
                variants.append(ProductVariant(
                    name=selected_variant,
                    price=product_data.get('mrp'),
                    discounted_price=product_data.get('offerPrice'),
                    availability="In Stock" if product_data.get('inStock', False) else "Out of Stock",
                    variant_id=str(product_data.get('selectedVariantId', ''))
                ))
        
        except Exception as e:
            logger.warning(f"Error extracting variants from JSON: {e}")
        
        return variants
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Extract product description"""
        desc_selectors = [
            '.product-description', 
            '[data-testid="product-description"]',
            '.description',
            '.about-product',
            '.product-details'
        ]
        return self._get_text_by_selectors(soup, desc_selectors, "")
    
    def _extract_key_features(self, soup: BeautifulSoup) -> List[str]:
        """Extract key features list"""
        features = []
        feature_selectors = [
            '.key-features li',
            '.features li',
            '.highlights li',
            '.product-features li'
        ]
        
        for selector in feature_selectors:
            elements = soup.select(selector)
            if elements:
                features = [elem.get_text(strip=True) for elem in elements]
                break
        
        return features
    
    def _extract_ingredients(self, soup: BeautifulSoup) -> List[str]:
        """Extract ingredients list"""
        ingredients = []
        ing_selectors = [
            '.ingredients',
            '.ingredient-list',
            '[data-testid="ingredients"]'
        ]
        
        for selector in ing_selectors:
            element = soup.select_one(selector)
            if element:
                # Try to find list items first
                li_elements = element.find_all('li')
                if li_elements:
                    ingredients = [li.get_text(strip=True) for li in li_elements]
                else:
                    # If no list, split by common delimiters
                    text = element.get_text(strip=True)
                    ingredients = [ing.strip() for ing in re.split(r'[,;]', text) if ing.strip()]
                break
        
        return ingredients
    
    def _extract_how_to_use(self, soup: BeautifulSoup) -> str:
        """Extract how to use instructions"""
        use_selectors = [
            '.how-to-use',
            '.usage-instructions',
            '.directions',
            '[data-testid="how-to-use"]'
        ]
        return self._get_text_by_selectors(soup, use_selectors, "")
    
    def _extract_images(self, soup: BeautifulSoup) -> List[str]:
        """Extract product images"""
        images = []
        img_selectors = [
            '.product-images img',
            '.image-gallery img',
            '.product-gallery img',
            '[data-testid="product-image"] img'
        ]
        
        for selector in img_selectors:
            img_elements = soup.select(selector)
            if img_elements:
                for img in img_elements:
                    src = img.get('src') or img.get('data-src')
                    if src and src not in images:
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = urljoin(self.base_url, src)
                        images.append(src)
        
        return list(set(images))  # Remove duplicates
    
    def _extract_variants(self, soup: BeautifulSoup) -> List[ProductVariant]:
        """Extract product variants (size, color, etc.)"""
        variants = []
        
        # Look for size variants
        size_selectors = [
            '.size-options .option',
            '.variant-size',
            '[data-testid="size-option"]'
        ]
        
        # Look for color variants
        color_selectors = [
            '.color-options .option',
            '.variant-color',
            '[data-testid="color-option"]'
        ]
        
        # Extract size variants
        for selector in size_selectors:
            elements = soup.select(selector)
            for elem in elements:
                name = elem.get_text(strip=True)
                if name:
                    variants.append(ProductVariant(
                        name=name,
                        price=None,
                        discounted_price=None,
                        availability="Unknown",
                        variant_id=elem.get('data-id')
                    ))
        
        # Extract color variants
        for selector in color_selectors:
            elements = soup.select(selector)
            for elem in elements:
                name = elem.get('title') or elem.get_text(strip=True)
                if name:
                    variants.append(ProductVariant(
                        name=name,
                        price=None,
                        discounted_price=None,
                        availability="Unknown",
                        variant_id=elem.get('data-id')
                    ))
        
        return variants
    
    def _extract_specifications(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract product specifications"""
        specs = {}
        
        spec_selectors = [
            '.specifications',
            '.product-specs',
            '.details-table',
            '[data-testid="specifications"]'
        ]
        
        for selector in spec_selectors:
            spec_section = soup.select_one(selector)
            if spec_section:
                # Look for key-value pairs in various formats
                rows = spec_section.find_all(['tr', 'div'])
                for row in rows:
                    cells = row.find_all(['td', 'span', 'div'])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        if key and value:
                            specs[key] = value
                break
        
        return specs
    
    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract product tags"""
        tags = []
        tag_selectors = [
            '.product-tags .tag',
            '.badges .badge',
            '.labels .label'
        ]
        
        for selector in tag_selectors:
            elements = soup.select(selector)
            if elements:
                tags = [elem.get_text(strip=True) for elem in elements]
                break
        
        return tags
    
    def _extract_availability(self, soup: BeautifulSoup) -> str:
        """Extract availability status"""
        avail_selectors = [
            '.availability',
            '.stock-status',
            '[data-testid="availability"]'
        ]
        return self._get_text_by_selectors(soup, avail_selectors, "Unknown")
    
    def _extract_delivery_info(self, soup: BeautifulSoup) -> str:
        """Extract delivery information"""
        delivery_selectors = [
            '.delivery-info',
            '.shipping-info',
            '[data-testid="delivery-info"]'
        ]
        return self._get_text_by_selectors(soup, delivery_selectors, "")
    
    def _extract_return_policy(self, soup: BeautifulSoup) -> str:
        """Extract return policy"""
        return_selectors = [
            '.return-policy',
            '.returns-info',
            '[data-testid="return-policy"]'
        ]
        return self._get_text_by_selectors(soup, return_selectors, "")
    
    def _extract_seller_info(self, soup: BeautifulSoup) -> SellerInfo:
        """Extract seller/brand information"""
        seller_name_selectors = ['.seller-name', '.brand-store', '[data-testid="seller-name"]']
        seller_name = self._get_text_by_selectors(soup, seller_name_selectors, "Unknown Seller")
        
        brand_name_selectors = ['.brand-name', '[data-testid="brand-name"]']
        brand_name = self._get_text_by_selectors(soup, brand_name_selectors, "Unknown Brand")
        
        return SellerInfo(
            seller_name=seller_name,
            seller_id=None,
            brand_name=brand_name,
            brand_id=None,
            seller_rating=None,
            seller_reviews_count=None,
            brand_description=None,
            official_store=False
        )
    
    def _extract_reviews_with_driver(self, driver, product_url: str) -> List[Review]:
        """Extract product reviews by navigating to dedicated reviews page"""
        reviews = []
        
        try:
            # First, try to get product ID and SKU from the current page
            product_id, sku_id = self._extract_product_and_sku_ids(product_url, driver)
            
            if product_id:
                # Extract the product slug from the current URL for the reviews URL
                product_slug = self._extract_product_slug(product_url)
                
                # Navigate to the dedicated reviews page
                if product_slug:
                    reviews_url = f"{self.base_url}/{product_slug}/reviews/{product_id}"
                else:
                    # Fallback to a generic reviews URL pattern
                    reviews_url = f"{self.base_url}/reviews/{product_id}"
                
                if sku_id:
                    reviews_url += f"?skuId={sku_id}&ptype=reviews"
                else:
                    reviews_url += "?ptype=reviews"
                
                logger.info(f"Navigating to reviews page: {reviews_url}")
                driver.get(reviews_url)
                self.random_delay()
                
                # Handle any popups
                self._handle_popups_with_driver(driver)
                
                # Wait for reviews to load
                try:
                    WebDriverWait(driver, 15).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='review-card']")),
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".review-card")),
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".consumer-review")),
                            EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='review']"))
                        )
                    )
                except TimeoutException:
                    logger.warning("No reviews found on dedicated reviews page")
                    return self._extract_reviews_from_current_page_driver(driver)
                
                # Implement infinite scrolling to load all reviews
                reviews = self._scrape_reviews_with_infinite_scroll_driver(driver)
                
                if reviews:
                    logger.info(f"Successfully extracted {len(reviews)} reviews from dedicated page")
                    return reviews
            
            # Fallback to extracting from current product page
            logger.info("Falling back to current page review extraction")
            return self._extract_reviews_from_current_page_driver(driver)
            
        except Exception as e:
            logger.error(f"Error extracting reviews: {e}")
            return self._extract_reviews_from_current_page_driver(driver)

    def _extract_reviews(self, product_url: str) -> List[Review]:
        """Extract product reviews by navigating to dedicated reviews page"""
        if not self.driver:
            self.setup_driver()
        return self._extract_reviews_with_driver(self.driver, product_url)

    def _extract_product_slug(self, product_url: str) -> str:
        """Extract the product slug from URL for building reviews URL"""
        try:
            # Extract everything between base URL and /p/
            # Example: https://www.nykaa.com/m-a-c-macximal-matte-lipstick/p/13784071
            # Should extract: m-a-c-macximal-matte-lipstick
            
            url_path = product_url.replace(self.base_url, '').strip('/')
            
            # Split by /p/ and take the first part
            if '/p/' in url_path:
                product_slug = url_path.split('/p/')[0]
                return product_slug
            
            # Alternative pattern: extract from path before product ID
            slug_match = re.search(r'/([^/]+)/p/\d+', product_url)
            if slug_match:
                return slug_match.group(1)
            
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting product slug: {e}")
            return None

    def _extract_product_and_sku_ids(self, product_url: str, driver=None) -> tuple:
        """Extract product ID and SKU ID from current page or URL"""
        product_id = None
        sku_id = None
        
        try:
            # Method 1: Extract from URL pattern
            # Pattern: /p/12345 or /product/12345 or ?productId=12345
            url_patterns = [
                r'/p/(\d+)',
                r'/product/(\d+)',
                r'productId[=:](\d+)',
                r'/(\d+)(?:/|\?|$)'  # Last number before query or end
            ]
            
            for pattern in url_patterns:
                url_match = re.search(pattern, product_url)
                if url_match:
                    product_id = url_match.group(1)
                    logger.info(f"Extracted product ID from URL pattern '{pattern}': {product_id}")
                    break
            
            # Method 2: Extract from current page JSON data if driver is provided
            if driver:
                try:
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    script_tags = soup.find_all('script')
                    
                    for script in script_tags:
                        if script.string and any(term in script.string for term in ['productId', 'parentId', 'skuId']):
                            try:
                                # Look for various ID patterns in JSON
                                id_patterns = [
                                    (r'"productId":"?(\d+)"?', 'productId'),
                                    (r'"parentId":"?(\d+)"?', 'parentId'),
                                    (r'"id":"?(\d+)"?', 'id'),
                                    (r'"skuId":"?(\d+)"?', 'skuId')
                                ]
                                
                                for pattern, field_name in id_patterns:
                                    matches = re.findall(pattern, script.string)
                                    if matches:
                                        if field_name == 'skuId':
                                            sku_id = matches[0]
                                            logger.info(f"Extracted SKU ID from {field_name}: {sku_id}")
                                        elif not product_id:  # Only set product_id if not already found
                                            product_id = matches[0]
                                            logger.info(f"Extracted product ID from {field_name}: {product_id}")
                                
                                if product_id:
                                    break
                            except Exception as e:
                                logger.warning(f"Error parsing script for IDs: {e}")
                                continue
                except Exception as e:
                    logger.warning(f"Error getting page source: {e}")
            
            # Method 3: Try to extract from URL query parameters
            if '?' in product_url:
                from urllib.parse import parse_qs, urlparse
                try:
                    parsed_url = urlparse(product_url)
                    query_params = parse_qs(parsed_url.query)
                    
                    if 'productId' in query_params:
                        product_id = query_params['productId'][0]
                        logger.info(f"Extracted product ID from query params: {product_id}")
                    if 'skuId' in query_params:
                        sku_id = query_params['skuId'][0]
                        logger.info(f"Extracted SKU ID from query params: {sku_id}")
                except Exception as e:
                    logger.warning(f"Error parsing URL query parameters: {e}")
            
            # Method 4: Fallback - try to extract from page title or breadcrumbs
            if not product_id and driver:
                try:
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    # Look for data attributes
                    product_containers = soup.find_all(['div', 'section'], attrs={'data-product-id': True})
                    for container in product_containers:
                        data_id = container.get('data-product-id')
                        if data_id and data_id.isdigit():
                            product_id = data_id
                            logger.info(f"Extracted product ID from data attribute: {product_id}")
                            break
                except Exception as e:
                    logger.warning(f"Error parsing page for data attributes: {e}")
            
            logger.info(f"Final extracted IDs - Product ID: {product_id}, SKU ID: {sku_id}")
            return product_id, sku_id
            
        except Exception as e:
            logger.warning(f"Error extracting product/SKU IDs: {e}")
            return None, None

    def _scrape_reviews_with_infinite_scroll_driver(self, driver):
        """Scrape reviews with infinite scrolling to get all available reviews"""
        reviews = []
        seen_reviews = set()
        scroll_attempts = 0
        max_scroll_attempts = 100  # Increase attempts to get more reviews
        consecutive_no_new_reviews = 0
        max_consecutive_no_new = 8  # Allow more attempts before giving up
        
        try:
            # Wait for the page to fully load
            time.sleep(5)
            
            while scroll_attempts < max_scroll_attempts and consecutive_no_new_reviews < max_consecutive_no_new:
                # Get current page reviews
                current_reviews = self._extract_reviews_from_current_reviews_page_driver(driver)
                new_reviews_count = 0
                
                for review in current_reviews:
                    # Create a unique identifier for each review to avoid duplicates
                    review_identifier = f"{review.user_info.username}_{review.rating}_{review.content[:50]}"
                    if review_identifier not in seen_reviews:
                        seen_reviews.add(review_identifier)
                        reviews.append(review)
                        new_reviews_count += 1
                
                logger.info(f"Scroll {scroll_attempts + 1}: Found {len(current_reviews)} reviews, {new_reviews_count} new. Total: {len(reviews)}")
                
                if new_reviews_count == 0:
                    consecutive_no_new_reviews += 1
                else:
                    consecutive_no_new_reviews = 0
                
                # Scroll down to load more reviews
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.random_delay()
                
                # Try to click "Load More" or "Show More" buttons if present
                load_more_selectors = [
                    "button:contains('Load more')",
                    "button:contains('Show more')",
                    ".load-more-reviews",
                    ".show-more-reviews",
                    "[aria-label*='Load more']",
                    "[aria-label*='Show more']"
                ]
                
                button_clicked = False
                for selector in load_more_selectors:
                    try:
                        if ":contains" in selector:
                            # Handle contains selector manually since Selenium doesn't support it
                            if "Load more" in selector:
                                buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Load more')]")
                            elif "Show more" in selector:
                                buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Show more')]")
                            else:
                                buttons = []
                        else:
                            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        for button in buttons:
                            if button.is_displayed() and button.is_enabled():
                                driver.execute_script("arguments[0].click();", button)
                                self.random_delay()
                                button_clicked = True
                                logger.info(f"Clicked load more button: {selector}")
                                break
                        
                        if button_clicked:
                            break
                    except Exception as e:
                        logger.debug(f"Error with load more selector {selector}: {e}")
                        continue
                
                scroll_attempts += 1
                
                # Add a small delay between scrolls
                time.sleep(1)
        
        except Exception as e:
            logger.error(f"Error during infinite scroll review extraction: {e}")
        
        logger.info(f"Completed review extraction with infinite scroll. Total reviews: {len(reviews)}")
        return reviews

    def _extract_reviews_from_current_reviews_page_driver(self, driver):
        """Extract reviews from the current reviews page HTML using reliable selectors"""
        reviews = []
        
        try:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Look for review containers using more reliable selectors
            # Based on the HTML analysis, reviews are in divs with specific structure
            review_selectors = [
                # Look for divs containing "Verified Buyers" text
                "div:has(span:contains('Verified Buyers'))",
                # Look for divs containing star ratings
                "div:has(svg[title='star'])",
                # Look for divs containing "Helpful" text  
                "div:has(span:contains('Helpful'))",
                # Look for sections with userInfoSection
                "div:has(.userInfoSection)",
                # Generic review-like containers
                "div[class*='z7l7ua']",  # From the HTML analysis
                "section[class*='review']",
                "article[class*='review']",
            ]
            
            review_elements = []
            
            # Try to find review containers
            for selector in review_selectors:
                try:
                    if ":has" in selector or ":contains" in selector:
                        # Handle these with BeautifulSoup differently
                        if "Verified Buyers" in selector:
                            # Find elements containing "Verified Buyers" text
                            elements = soup.find_all(text=re.compile(r'Verified Buyers', re.I))
                            parents = []
                            for elem in elements:
                                # Go up the DOM tree to find the review container
                                parent = elem.parent
                                for _ in range(5):  # Go up max 5 levels
                                    if parent and parent.name == 'div':
                                        # Check if this looks like a review container
                                        if len(parent.find_all(text=re.compile(r'star|helpful|rating', re.I))) > 0:
                                            parents.append(parent)
                                            break
                                    if parent:
                                        parent = parent.parent
                                    else:
                                        break
                            if parents:
                                review_elements = parents
                                logger.info(f"Found {len(review_elements)} review elements using Verified Buyers text")
                                break
                        
                        elif "star" in selector:
                            # Find star SVG elements and get their containers
                            star_elements = soup.find_all('svg', title=re.compile(r'star', re.I))
                            parents = []
                            for star in star_elements:
                                parent = star.parent
                                for _ in range(8):  # Go up max 8 levels to find review container
                                    if parent and len(str(parent)) > 500:  # Substantial content
                                        if parent.find(text=re.compile(r'Verified|Helpful|[0-9]+.*found.*helpful', re.I)):
                                            parents.append(parent)
                                            break
                                    if parent:
                                        parent = parent.parent
                                    else:
                                        break
                            if parents:
                                review_elements = parents
                                logger.info(f"Found {len(review_elements)} review elements using star SVG")
                                break
                                
                        elif "Helpful" in selector:
                            # Find elements containing "Helpful" text
                            helpful_elements = soup.find_all(text=re.compile(r'\d+.*people found this helpful', re.I))
                            parents = []
                            for elem in helpful_elements:
                                parent = elem.parent
                                for _ in range(8):  # Go up max 8 levels
                                    if parent and len(str(parent)) > 300:  # Substantial content
                                        if parent.find(text=re.compile(r'Verified', re.I)):
                                            parents.append(parent)
                                            break
                                    if parent:
                                        parent = parent.parent
                                    else:
                                        break
                            if parents:
                                review_elements = parents
                                logger.info(f"Found {len(review_elements)} review elements using helpful text")
                                break
                    else:
                        # Standard CSS selector
                        elements = soup.select(selector)
                        if elements:
                            review_elements = elements
                            logger.info(f"Found {len(review_elements)} review elements with selector: {selector}")
                            break
                            
                except Exception as e:
                    logger.warning(f"Error with selector {selector}: {e}")
                    continue
            
            # If no luck with semantic selectors, try the known working class from HTML analysis
            if not review_elements:
                # From the HTML, we know reviews are in css-z7l7ua containers
                review_elements = soup.select("div[class*='z7l7ua']")
                if review_elements:
                    logger.info(f"Found {len(review_elements)} review elements using fallback class selector")
            
            # Parse each review element
            for review_elem in review_elements[:50]:  # Limit to 50 reviews
                review = self._parse_review_from_reviews_page_semantic(review_elem)
                if review:
                    reviews.append(review)
        
        except Exception as e:
            logger.error(f"Error extracting reviews from current reviews page: {e}")
        
        return reviews

    def _parse_review_from_reviews_page_semantic(self, review_elem) -> Optional[Review]:
        """Parse individual review element using semantic/reliable selectors"""
        try:
            # Extract username using semantic approaches
            username = "Anonymous"
            
            # Look for username in various ways
            username_methods = [
                # Find text near "Verified Buyers"
                lambda: self._find_text_before_pattern(review_elem, r'Verified Buyers?', max_distance=100),
                # Find bold/strong text that looks like names
                lambda: self._find_name_in_element(review_elem, ['strong', 'b', 'span']),
                # Find text in common username locations
                lambda: self._get_text_by_selectors_element(review_elem, ['[class*="amd8cf"]'], ""),
            ]
            
            for method in username_methods:
                try:
                    result = method()
                    if result and len(result) > 1 and len(result) < 50:  # Reasonable name length
                        username = result
                        break
                except Exception:
                    continue
            
            # Extract verified buyer status
            verified_purchase = bool(review_elem.find(text=re.compile(r'Verified Buyers?', re.I)))
            
            # Extract rating using semantic approaches
            rating = 0
            
            # Look for star SVG elements
            star_elements = review_elem.find_all('svg', title=re.compile(r'star', re.I))
            if star_elements:
                # Count filled/active stars or look for rating number
                rating_text = ""
                # Look for number near stars
                star_parent = star_elements[0].parent
                if star_parent:
                    rating_text = star_parent.get_text()
                    rating_match = re.search(r'(\d+(?:\.\d+)?)', rating_text)
                    if rating_match:
                        rating = float(rating_match.group(1))
                        if rating > 5:  # Ensure it's in 1-5 scale
                            rating = 5
            
            # Fallback: look for rating in any text
            if rating == 0:
                all_text = review_elem.get_text()
                rating_patterns = [r'(\d)\s*[/\s]*5', r'(\d+(?:\.\d+)?)\s*star', r'Rating[:\s]*(\d+(?:\.\d+)?)']
                for pattern in rating_patterns:
                    match = re.search(pattern, all_text, re.I)
                    if match:
                        rating = float(match.group(1))
                        break
            
            # Extract review title
            title = ""
            title_methods = [
                # Look for quoted text (often review titles)
                lambda: self._find_quoted_text(review_elem),
                # Look for text in title-like elements
                lambda: self._get_text_by_selectors_element(review_elem, ['h1', 'h2', 'h3', 'h4', '[class*="tm4hnq"]'], ""),
            ]
            
            for method in title_methods:
                try:
                    result = method()
                    if result and len(result) > 3:
                        title = result.strip('"').strip()
                        break
                except Exception:
                    continue
            
            # Extract review content
            content = ""
            
            # Look for substantial text content
            content_methods = [
                # Look for paragraphs
                lambda: self._get_text_by_selectors_element(review_elem, ['p'], ""),
                # Look for divs with substantial text
                lambda: self._find_substantial_text(review_elem),
                # Look for known content classes
                lambda: self._get_text_by_selectors_element(review_elem, ['[class*="1n0nrdk"]'], ""),
            ]
            
            for method in content_methods:
                try:
                    result = method()
                    if result and len(result) > 10:  # Substantial content
                        content = result
                        # Clean up "Read More" text
                        content = re.sub(r'\.\.\..*Read More.*$', '...', content, flags=re.I)
                        break
                except Exception:
                    continue
            
            # Extract date
            date = ""
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{1,2}-\d{1,2}-\d{4})',
                r'(\d{4}-\d{1,2}-\d{1,2})',
                r'(\d{1,2}\s+\w+\s+\d{4})',
            ]
            
            all_text = review_elem.get_text()
            for pattern in date_patterns:
                match = re.search(pattern, all_text)
                if match:
                    date = match.group(1)
                    break
            
            # Extract helpful count
            helpful_count = 0
            helpful_patterns = [
                r'(\d+)\s*people found this helpful',
                r'Helpful\s*(\d+)',
                r'(\d+)\s*found.*helpful',
            ]
            
            for pattern in helpful_patterns:
                match = re.search(pattern, all_text, re.I)
                if match:
                    helpful_count = int(match.group(1))
                    break
            
            # Extract review images
            images = []
            img_elements = review_elem.find_all('img')
            for img in img_elements:
                src = img.get('src')
                if src and any(keyword in src.lower() for keyword in ['review', 'prod-review']):
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    images.append(src)
            
            # Only create review if we have minimum required information
            if username and (content or title) and rating > 0:
                user_info = UserInfo(
                    username=username,
                    user_id=None,
                    verified_purchase=verified_purchase,
                    review_count=None,
                    location=None,
                    join_date=None
                )
                
                return Review(
                    review_id=None,
                    user_info=user_info,
                    rating=int(rating),
                    title=title,
                    content=content,
                    date=date,
                    helpful_count=helpful_count,
                    verified_purchase=verified_purchase,
                    images=images,
                    pros=[],
                    cons=[]
                )
            
        except Exception as e:
            logger.warning(f"Error parsing review using semantic selectors: {e}")
        
        return None

    def _find_text_before_pattern(self, element, pattern: str, max_distance: int = 100) -> str:
        """Find text that appears before a specific pattern"""
        try:
            text = element.get_text()
            match = re.search(pattern, text, re.I)
            if match:
                before_text = text[:match.start()]
                # Look for the last substantial word before the pattern
                words = before_text.strip().split()
                if words:
                    # Return the last 1-2 words that look like a name
                    potential_name = ' '.join(words[-2:]) if len(words) >= 2 else words[-1]
                    if len(potential_name) > 2 and len(potential_name) < 50:
                        return potential_name
        except Exception:
            pass
        return ""

    def _find_name_in_element(self, element, tags: List[str]) -> str:
        """Find text in specific tags that looks like a name"""
        try:
            for tag in tags:
                tag_elements = element.find_all(tag)
                for tag_elem in tag_elements:
                    text = tag_elem.get_text(strip=True)
                    # Check if this looks like a name (not too long, not common UI text)
                    if (text and 2 < len(text) < 50 and 
                        not any(word in text.lower() for word in ['verified', 'buyers', 'helpful', 'star', 'rating', 'review'])):
                        return text
        except Exception:
            pass
        return ""

    def _find_quoted_text(self, element) -> str:
        """Find text enclosed in quotes"""
        try:
            text = element.get_text()
            # Look for text in quotes
            quote_patterns = [r'"([^"]+)"', r'"([^"]+)"', r"'([^']+)'"]
            for pattern in quote_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    if 5 < len(match) < 200:  # Reasonable title length
                        return match
        except Exception:
            pass
        return ""

    def _find_substantial_text(self, element) -> str:
        """Find the most substantial text content in an element"""
        try:
            # Get all text nodes and find the longest substantial one
            texts = []
            for child in element.descendants:
                if hasattr(child, 'string') and child.string and len(child.string.strip()) > 20:
                    text = child.string.strip()
                    # Skip if it's likely UI text
                    if not any(word in text.lower() for word in ['verified', 'helpful', 'star', 'rating', 'buyers']):
                        texts.append(text)
            
            # Return the longest text
            if texts:
                return max(texts, key=len)
        except Exception:
            pass
        return ""

    def _extract_reviews_from_current_page_driver(self, driver):
        """Fallback method to extract reviews from current product page"""
        reviews = []
        
        try:
            # Get the current page source for review extraction
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Look for reviews in the JSON data first
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'latestReviews' in script.string:
                    try:
                        # Extract reviews from the JSON data
                        reviews_data = self._extract_reviews_from_json(script.string)
                        if reviews_data:
                            reviews.extend(reviews_data)
                            logger.info(f"Extracted {len(reviews_data)} reviews from JSON data")
                            break
                    except Exception as e:
                        logger.warning(f"Error extracting reviews from JSON: {e}")
                        continue
            
            # If no reviews found in JSON, try HTML extraction
            if not reviews:
                logger.info("No reviews found in JSON, trying HTML extraction")
                reviews = self._extract_reviews_from_html(soup)
            
        except Exception as e:
            logger.error(f"Error extracting reviews from current page: {e}")
        
        logger.info(f"Total reviews extracted from current page: {len(reviews)}")
        return reviews[:50]  # Limit to 50 reviews per product

    def _extract_reviews_from_json(self, script_content: str) -> List[Review]:
        """Extract reviews from JSON data in script tags"""
        reviews = []
        
        try:
            # Method 1: Look for latestReviews directly
            latest_reviews_pattern = r'"latestReviews"\s*:\s*(\[(?:[^[\]]+|\[[^\]]*\])*\])'
            latest_reviews_match = re.search(latest_reviews_pattern, script_content, re.DOTALL)
            
            if latest_reviews_match:
                try:
                    reviews_json = latest_reviews_match.group(1)
                    reviews_data = json.loads(reviews_json)
                    
                    if isinstance(reviews_data, list):
                        for review_data in reviews_data:
                            if isinstance(review_data, dict):
                                review = self._parse_review_from_json(review_data)
                                if review:
                                    reviews.append(review)
                except json.JSONDecodeError as e:
                    logger.warning(f"Error parsing latestReviews JSON: {e}")
            
            # Method 2: Extract from full preloaded state if method 1 failed
            if not reviews:
                try:
                    preloaded_data = self._extract_json_data_safely(script_content, 'window.__PRELOADED_STATE__ = ')
                    if preloaded_data:
                        product_details = preloaded_data.get('productPage', {}).get('productDetails', {})
                        if product_details and 'latestReviews' in product_details:
                            latest_reviews = product_details['latestReviews']
                            if isinstance(latest_reviews, list):
                                for review_data in latest_reviews:
                                    review = self._parse_review_from_json(review_data)
                                    if review:
                                        reviews.append(review)
                except Exception as e:
                    logger.warning(f"Error extracting reviews from preloaded state: {e}")
        
        except Exception as e:
            logger.warning(f"Error parsing reviews from JSON: {e}")
        
        return reviews

    def _parse_review_from_json(self, review_data: dict) -> Optional[Review]:
        """Parse individual review from JSON data"""
        try:
            # Extract user information
            user_name = review_data.get('name', 'Anonymous')
            
            # Extract rating
            rating = int(review_data.get('rating', 0))
            
            # Extract review title and content
            title = review_data.get('title', '')
            content = review_data.get('description', '')
            
            # Extract date
            date = review_data.get('createdOn', review_data.get('createdOnText', ''))
            
            # Extract helpful count
            helpful_count = int(review_data.get('likeCount', 0))
            
            # Check if verified purchase
            verified_purchase = review_data.get('isBuyer', False)
            
            # Extract review images
            images = []
            review_images = review_data.get('images', [])
            if isinstance(review_images, list):
                for img_url in review_images:
                    if isinstance(img_url, str) and img_url.strip():
                        images.append(img_url)
            
            # Create user info
            user_info = UserInfo(
                username=user_name,
                user_id=None,
                verified_purchase=verified_purchase,
                review_count=None,
                location=None,
                join_date=None
            )
            
            return Review(
                review_id=str(review_data.get('id', '')),
                user_info=user_info,
                rating=rating,
                title=title,
                content=content,
                date=date,
                helpful_count=helpful_count,
                verified_purchase=verified_purchase,
                images=images,
                pros=[],
                cons=[]
            )
            
        except Exception as e:
            logger.warning(f"Error parsing review from JSON: {e}")
            return None

    def _extract_reviews_from_html(self, soup: BeautifulSoup) -> List[Review]:
        """Extract reviews from HTML when JSON extraction fails"""
        reviews = []
        
        try:
            review_selectors = [
                '.review-item',
                '.review-card',
                '[data-testid="review"]',
                '.user-review',
                '.consumer-review',
                'div[class*="review"]'
            ]
            
            for selector in review_selectors:
                review_elements = soup.select(selector)
                if review_elements:
                    logger.info(f"Found {len(review_elements)} review elements with selector: {selector}")
                    for review_elem in review_elements[:20]:  # Limit to 20 reviews per product
                        review = self._parse_review(review_elem)
                        if review:
                            reviews.append(review)
                    break
            
        except Exception as e:
            logger.error(f"Error extracting reviews from HTML: {e}")
        
        return reviews
    
    def _load_more_reviews(self):
        """Try to load more reviews by clicking load more buttons"""
        try:
            for _ in range(3):  # Try to load more reviews 3 times
                load_more_selectors = [
                    "[aria-label='Load more reviews']",
                    ".load-more-reviews",
                    ".show-more-reviews"
                ]
                
                button_found = False
                for selector in load_more_selectors:
                    try:
                        button = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if button.is_displayed() and button.is_enabled():
                            self.driver.execute_script("arguments[0].click();", button)
                            self.random_delay()
                            button_found = True
                            break
                    except NoSuchElementException:
                        continue
                
                if not button_found:
                    break
                    
        except Exception as e:
            logger.warning(f"Error loading more reviews: {e}")
    
    def _parse_review(self, review_elem) -> Optional[Review]:
        """Parse individual review element"""
        try:
            # Extract user information
            username = self._get_text_by_selectors(
                review_elem, 
                ['.username', '.reviewer-name', '[data-testid="username"]'], 
                "Anonymous"
            )
            
            # Extract rating
            rating_elem = review_elem.select_one('.rating, .stars, [data-testid="rating"]')
            rating = 0
            if rating_elem:
                rating_text = rating_elem.get_text() or rating_elem.get('title', '')
                rating = self._extract_rating(rating_text)
            
            # Extract review title
            title = self._get_text_by_selectors(
                review_elem,
                ['.review-title', '.title', '[data-testid="review-title"]'],
                ""
            )
            
            # Extract review content
            content = self._get_text_by_selectors(
                review_elem,
                ['.review-content', '.review-text', '[data-testid="review-content"]'],
                ""
            )
            
            # Extract date
            date = self._get_text_by_selectors(
                review_elem,
                ['.review-date', '.date', '[data-testid="review-date"]'],
                ""
            )
            
            # Extract helpful count
            helpful_text = self._get_text_by_selectors(
                review_elem,
                ['.helpful-count', '.likes', '[data-testid="helpful-count"]'],
                "0"
            )
            helpful_count = self._extract_number(helpful_text)
            
            # Check if verified purchase
            verified_elem = review_elem.select_one('.verified-purchase, .verified')
            verified_purchase = verified_elem is not None
            
            # Extract review images
            img_elements = review_elem.select('.review-images img, .user-images img')
            images = []
            for img in img_elements:
                src = img.get('src') or img.get('data-src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    images.append(src)
            
            user_info = UserInfo(
                username=username,
                user_id=None,
                verified_purchase=verified_purchase,
                review_count=None,
                location=None,
                join_date=None
            )
            
            return Review(
                review_id=None,
                user_info=user_info,
                rating=rating,
                title=title,
                content=content,
                date=date,
                helpful_count=helpful_count,
                verified_purchase=verified_purchase,
                images=images,
                pros=[],
                cons=[]
            )
            
        except Exception as e:
            logger.warning(f"Error parsing review: {e}")
            return None
    
    def _get_text_by_selectors(self, soup, selectors: List[str], default: str = "") -> str:
        """Get text content using multiple CSS selectors"""
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if text:
                    return text
        return default
    
    def _get_text_by_selectors_element(self, element, selectors: List[str], default: str = "") -> str:
        """Get text content from element using multiple CSS selectors"""
        for selector in selectors:
            sub_element = element.select_one(selector)
            if sub_element:
                text = sub_element.get_text(strip=True)
                if text:
                    return text
        return default
    
    def _extract_price(self, price_text: str) -> float:
        """Extract numeric price from text"""
        if not price_text:
            return 0.0
        
        # Remove currency symbols and extract numbers
        price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
        if price_match:
            return float(price_match.group())
        return 0.0
    
    def _extract_rating(self, rating_text: str) -> float:
        """Extract numeric rating from text"""
        if not rating_text:
            return 0.0
        
        rating_match = re.search(r'(\d+\.?\d*)', rating_text)
        if rating_match:
            return float(rating_match.group(1))
        return 0.0
    
    def _extract_number(self, text: str) -> int:
        """Extract number from text"""
        if not text:
            return 0
        
        number_match = re.search(r'(\d+)', text.replace(',', ''))
        if number_match:
            return int(number_match.group(1))
        return 0
    
    def _extract_product_id(self, product_url: str) -> str:
        """Extract product ID from URL"""
        # Try to extract ID from URL patterns
        patterns = [
            r'/p/([^/]+)',
            r'product/([^/]+)',
            r'pid=([^&]+)',
            r'/(\d+)/'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, product_url)
            if match:
                return match.group(1)
        
        # Fallback to URL hash
        return str(hash(product_url))
    
    def _scrape_reviews_with_infinite_scroll(self) -> List[Review]:
        """Scrape reviews with infinite scrolling to get all available reviews"""
        if not self.driver:
            self.setup_driver()
        return self._scrape_reviews_with_infinite_scroll_driver(self.driver)

    def _extract_reviews_from_current_reviews_page(self) -> List[Review]:
        """Extract reviews from the current reviews page HTML using reliable selectors"""
        if not self.driver:
            self.setup_driver()
        return self._extract_reviews_from_current_reviews_page_driver(self.driver)

    def _extract_reviews_from_current_page(self) -> List[Review]:
        """Fallback method to extract reviews from current product page"""
        if not self.driver:
            self.setup_driver()
        return self._extract_reviews_from_current_page_driver(self.driver)
    
    def scrape_keywords(self, keywords: List[str], max_products_per_keyword: int = 20) -> Dict[str, Any]:
        """
        Main method to scrape products for multiple keywords using multi-threading
        
        Args:
            keywords: List of search keywords
            max_products_per_keyword: Maximum products to scrape per keyword
            
        Returns:
            Dictionary containing all scraped data
        """
        logger.info(f"Starting multi-threaded scrape for keywords: {keywords}")
        logger.info(f"Using {self.max_threads} threads for parallel processing")
        
        self.scraped_data['scrape_metadata']['keywords_searched'] = keywords
        
        all_scraped_products = []
        
        # Use ThreadPoolExecutor for parallel keyword processing
        with ThreadPoolExecutor(max_workers=self.max_threads, thread_name_prefix="NykaaScraper") as executor:
            # Submit all keyword scraping tasks
            future_to_keyword = {}
            for keyword in keywords:
                future = executor.submit(self._scrape_keyword_thread, keyword, max_products_per_keyword)
                future_to_keyword[future] = keyword
            
            # Collect results as they complete
            for future in tqdm(as_completed(future_to_keyword), total=len(keywords), desc="Scraping keywords"):
                keyword = future_to_keyword[future]
                try:
                    scraped_products = future.result()
                    logger.info(f"Completed keyword '{keyword}': {len(scraped_products)} products")
                    
                    # Thread-safe data aggregation
                    with self._data_lock:
                        all_scraped_products.extend(scraped_products)
                        # Count total reviews
                        for product in scraped_products:
                            self.scraped_data['scrape_metadata']['total_reviews'] += len(product.get('reviews', []))
                            
                except Exception as e:
                    logger.error(f"Error processing keyword '{keyword}': {e}")
                    continue
        
        # Update scraped data
        self.scraped_data['products'] = all_scraped_products
        self.scraped_data['scrape_metadata']['total_products'] = len(all_scraped_products)
        
        logger.info(f"Multi-threaded scraping completed. Total products: {len(all_scraped_products)}")
        return self.scraped_data
    
    def save_data(self, filename: str = None):
        """Save scraped data to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"nykaa_scraped_data_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.scraped_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Data saved to {filename}")
            
            # Also save a summary report
            summary_filename = filename.replace('.json', '_summary.txt')
            self._save_summary_report(summary_filename)
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def _save_summary_report(self, filename: str):
        """Save a summary report of the scraped data"""
        try:
            total_products = self.scraped_data['scrape_metadata']['total_products']
            total_reviews = self.scraped_data['scrape_metadata']['total_reviews']
            keywords = self.scraped_data['scrape_metadata']['keywords_searched']
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("NYKAA SCRAPER SUMMARY REPORT\n")
                f.write("=" * 40 + "\n\n")
                f.write(f"Scrape Date: {self.scraped_data['scrape_metadata']['scrape_date']}\n")
                f.write(f"Keywords Searched: {', '.join(keywords)}\n")
                f.write(f"Total Products Scraped: {total_products}\n")
                f.write(f"Total Reviews Collected: {total_reviews}\n\n")
                
                if self.scraped_data['products']:
                    f.write("PRODUCT BREAKDOWN:\n")
                    f.write("-" * 20 + "\n")
                    
                    brands = {}
                    categories = {}
                    
                    for product in self.scraped_data['products']:
                        brand = product.get('brand', 'Unknown')
                        category = product.get('category', 'Unknown')
                        
                        brands[brand] = brands.get(brand, 0) + 1
                        categories[category] = categories.get(category, 0) + 1
                    
                    f.write("\nTop Brands:\n")
                    for brand, count in sorted(brands.items(), key=lambda x: x[1], reverse=True)[:10]:
                        f.write(f"  {brand}: {count} products\n")
                    
                    f.write("\nCategories:\n")
                    for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                        f.write(f"  {category}: {count} products\n")
            
            logger.info(f"Summary report saved to {filename}")
            
        except Exception as e:
            logger.error(f"Error saving summary report: {e}")
    
    def cleanup(self):
        """Clean up resources including thread-local drivers"""
        try:
            # Clean up main driver
            if self.driver:
                self.driver.quit()
                self.driver = None
            
            # Clean up thread-local drivers
            if hasattr(self._thread_local, 'driver') and self._thread_local.driver:
                self._thread_local.driver.quit()
                self._thread_local.driver = None
            
            # Close session
            if self.session:
                self.session.close()
                
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


def main():
    """Main function to run the scraper"""
    
    # Configuration
    KEYWORDS = [
        "eyeshadow",
        "eyeliner"
    ]
    
    MAX_PRODUCTS_PER_KEYWORD = 40  # Adjust based on needs
    MAX_THREADS = 2  # Number of threads for parallel processing
    HEADLESS = True  # Set to False to see browser in action
    
    # Initialize scraper with thread configuration
    scraper = NykaaScraper(headless=HEADLESS, delay_range=(2, 4), max_threads=MAX_THREADS)
    
    try:
        # Run scraping
        logger.info("Starting Nykaa scraper...")
        data = scraper.scrape_keywords(KEYWORDS, MAX_PRODUCTS_PER_KEYWORD)
        
        # Save data
        scraper.save_data()
        
        logger.info("Scraping completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
    finally:
        # Cleanup
        scraper.cleanup()
        logger.info("Cleanup completed")


if __name__ == "__main__":
    main() 