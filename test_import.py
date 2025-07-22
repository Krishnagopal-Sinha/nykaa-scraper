#!/usr/bin/env python3

import sys
print(f"Python version: {sys.version}")
print(f"Current directory: {sys.path[0]}")

try:
    print("Testing basic imports...")
    import requests
    import json
    import time
    import random
    import re
    import logging
    import os
    print("✅ Basic imports successful")
    
    print("Testing selenium imports...")
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    print("✅ Selenium imports successful")
    
    print("Testing BeautifulSoup...")
    from bs4 import BeautifulSoup
    print("✅ BeautifulSoup import successful")
    
    print("Testing fake_useragent...")
    from fake_useragent import UserAgent
    print("✅ fake_useragent import successful")
    
    print("Attempting to import nykaa_scraper...")
    from nykaa_scraper import NykaaScraper
    print("✅ nykaa_scraper import successful")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc() 