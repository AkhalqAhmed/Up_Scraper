import time
import json
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI
from dotenv import load_dotenv
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os
import re
import json
import textwrap

load_dotenv()
Open_Api_Key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=Open_Api_Key)

system_prompt = os.getenv("SYSTEM_PROMPT")


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def call_gpt(messages):
    """Call GPT and extract JSON from response."""
    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=messages,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        json_str = match.group(1) if match else content
        return json.loads(json_str)
    except Exception as e:
        print("GPT call failed:", e)
        return []


def extract_and_structure_car_listings(html, batch_chars, btn_count=1):
    """
    Step 1: Extract raw car data in chunks.
    Step 2: Send the combined raw data back to GPT for structured formatting.
    """
    # STEP 1: Chunk HTML into parts
    html_chunks = textwrap.wrap(html, width=batch_chars)
    raw_car_data = []

    for i, chunk in enumerate(html_chunks):
        messages = [
            {
                "role": "system",
                "content": (
                    "You're a web scraping assistant. Extract all car listing info (as much detail as possible) from this raw HTML. "
                    "Be lenient with formatting — focus on identifying cars and their key data like make, model, year, price, color, VIN, etc. "
                    "Return them as a JSON array of raw unstructured objects, wrapped in triple backticks like ```json ... ```."
                )
            },
            {
                "role": "user",
                "content": f"This is part {i+1} of the HTML for page {btn_count}:\n\n{chunk}"
            }
        ]

        print(f"Extracting raw data from batch {i+1}/{len(html_chunks)}...")
        raw_batch = call_gpt(messages)
        raw_car_data.extend(raw_batch)

    print(f"\nExtracted {len(raw_car_data)} raw car listings. Now structuring...")

    # STEP 2: Structure all raw listings
    final_messages = [
        {
            "role": "system",
            "content": (
                "You are a smart data normalizer. You will be given a list of raw car listings and your job is to convert them into the following clean structure:\n\n"
                "[{ \"id\": car_id, \"make\": make, \"model\": model, \"year\": year, \"price\": price, "
                "\"mileage\": 0, \"color\": color, \"vin\": vin, \"stockNumber\": stock, "
                "\"condition\": new_or_used, \"detail_url\": detail_url }]\n\n"
                "Return valid JSON wrapped in triple backticks."
            )
        },
        {
            "role": "user",
            "content": f"Here is a list of raw car listings extracted from HTML:\n\n{json.dumps(raw_car_data)}"
        }
    ]

    structured_cars = call_gpt(final_messages)
    print(f"Final structured listings count: {len(structured_cars)}")
    return structured_cars


def init_driver():

    CHROMEDRIVER_PATH = r'C:\Program Files\chromedriver-win64\chromedriver.exe'

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    # chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument('--enable-unsafe-swiftshader')

    service = Service(CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver


def wait_for_page_load(driver, timeout=15):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "ul.vehicle-card-grid li.vehicle-card"))
    )


def scroll_to_bottom(driver):
    scroll_pause_time = 2  # seconds between scrolls
    scroll_step = 650      # pixels per scroll

    last_height = driver.execute_script("return document.body.scrollHeight")
    current_scroll = 0

    while current_scroll < last_height:
        driver.execute_script(f"window.scrollTo(0, {current_scroll});")
        time.sleep(scroll_pause_time)
        current_scroll += scroll_step
        last_height = driver.execute_script("return document.body.scrollHeight")


def get_spec_detail(soup, label):
    label_elem = soup.find("span", string=lambda t: t and label in t)
    if label_elem:
        detail = label_elem.find_next_sibling("span", class_="spec-item-detail")
        if detail:
            return detail.get_text(strip=True)
    return "Unknown"


def get_all_car_listings():
    
    print("Starting to scrape car listings...")

    url = "https://www.diamondvalleyhonda.com/new-inventory/index.htm"
    driver = init_driver()
    driver.implicitly_wait(10)  # Set implicit wait for elements to load
    driver.get(url)
    wait_for_page_load(driver)
    
    scroll_to_bottom(driver)

    car_list = []
    btn_count = 2
    
    car_id = 1

    while True:
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # final_car_listings = extract_and_structure_car_listings(soup.prettify(), batch_chars=100500, btn_count=btn_count - 1)

        # print(f"Extracted {len(final_car_listings)} cars from page {btn_count - 1}.")
        cars = soup.select("ul.vehicle-card-grid li.vehicle-card[data-uuid]")
        
        print (f"Found {len(cars)} cars on this page.")
        for car in cars:
            
            if "placeholder-card" in car.get("class", []) or not car.get("data-uuid"):
                continue
            
            try:
                title_tag = car.select_one("h2.vehicle-card-title span")
                if not title_tag:
                    continue
                
                title = title_tag.get_text(strip=True)
                
                # print(f"Processing car title: {title}")
                detail_href = car.select_one("h2.vehicle-card-title a")["href"]
                detail_url = "https://www.diamondvalleyhonda.com" + detail_href if detail_href.startswith("/") else ""
                # print(f"Detail URL: {detail_url}")
                vin = car.select_one("li.vin").get_text(strip=True).replace("VIN", "").strip()
                # print(f" VIN: {vin}")
                stock = car.select_one("li.stockNumber").get_text(strip=True).replace("Stock #", "").strip()
                # print(f" Stock: {stock}")
                price_tag = car.select_one("dd.final-price span.price-value")
                price = float(price_tag.get_text(strip=True).replace("$", "").replace(",", "")) if price_tag else 0

                year = int(title.split()[0])
                make = title.split()[1]
                model = title.split()[2]
                model = " ".join(title.split()[2:])  # Join remaining parts for model

                print(f"Processing car ID: {car_id} {title} {make} {model} {year} {price} {vin} {stock}")

                car_list.append({
                    "id": car_id,
                    "make": make,
                    "model": model,
                    "year": year,
                    "price": price,
                    "mileage": 0,
                    "color": "Unknown",
                    "vin": vin,
                    "stockNumber": stock,
                    "condition": "new",
                    "detail_url": detail_url
                })

                car_id += 1
            except Exception as e:
                print(f"Error processing car ID {car_id}: {e}")
                print("Card HTML:")
                # print(car.prettify()[:1500])  # Limit output to avoid flooding
                continue
        
        try:
            # This finds the <a> tag inside the "Next" button
            next_btn = driver.find_element(By.CSS_SELECTOR, "li.pagination-next > a")

            # Optional: Check if button is disabled via class
            next_class = next_btn.get_attribute("class")
            if next_class and "disabled" in next_class:
                print("Next button is disabled. Stopping.")
                break

            print(f"Clicking next page: {next_btn.get_attribute('href')}")
            driver.execute_script("arguments[0].click();", next_btn)  # More reliable than next_btn.click()
            wait_for_page_load(driver)
            
            
            scroll_to_bottom(driver)  # Scroll to bottom after clicking next

        except NoSuchElementException:
            print("No Next button found — likely the last page.")
            break
        except Exception as e:
            print(f"Error clicking Next: {e}")
            break
    
    
    driver.quit()
    return car_list


def extract_car_details(car_list):
    
    print("Starting to extract car details...")
    
    driver = init_driver()
    driver.implicitly_wait(10)  # Set implicit wait for elements to load

    enriched = []

    for car in car_list:
        try:
            driver.get(car["detail_url"])

            body_html = driver.find_element(By.XPATH, "//body").get_attribute("innerHTML")
            soup = BeautifulSoup(body_html, "html.parser")
            
            
            # Parse quick specs
            spec_map = {}
            quick_specs = {
                "exteriorColor": "Exterior Color",
                "interiorColor": "Interior Color",
                "drivetrain": "Drivetrain",
                "engine": "Engine",
                "bodySeating": "Body/Seating",
                "vin": "VIN",
                "stockNumber": "Stock Number",
                "fuelEconomy": "Fuel Economy",
                "transmission": "Transmission"
            }

            for label, key in quick_specs.items():
                dt = soup.find("dt", string=lambda t: t and key in t)
                if dt:
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        spec_map[label] = dd.get_text(strip=True)

            # Highlighted & Included Features
            all_features = [li.get_text(strip=True) for li in soup.find_all("li")]

            def categorize(features):
                tech, interior, exterior, performance, standard, optional = [], [], [], [], [], []
                for f in features:
                    lower = f.lower()
                    if any(k in lower for k in ["bluetooth", "radio", "connect", "infotain"]):
                        tech.append(f)
                    elif any(k in lower for k in ["seat", "climate", "mirror", "temperature"]):
                        interior.append(f)
                    elif any(k in lower for k in ["headlight", "fog", "grille", "tail"]):
                        exterior.append(f)
                    elif any(k in lower for k in ["suspension", "steering", "cruise", "handling"]):
                        performance.append(f)
                    elif any(k in lower for k in ["window", "door", "lock", "brake", "alarm"]):
                        standard.append(f)
                    else:
                        optional.append(f)
                return tech, interior, exterior, performance, standard, optional

            tech, interior, exterior, performance, standard, optional = categorize(all_features)

            mpgCity, mpgHighway = "Unknown", "Unknown"
            if "fuelEconomy" in spec_map and "/" in spec_map["fuelEconomy"]:
                mpg_parts = spec_map["fuelEconomy"].split("/")
                mpgCity = mpg_parts[0].split()[0].strip()
                mpgHighway = mpg_parts[1].split()[0].strip()
                
            horsepower = get_spec_detail(soup, "Horsepower:")
            engineSize = get_spec_detail(soup, "Engine displacement:")
            torque = get_spec_detail(soup, "Torque:")
            fuelCapacity = get_spec_detail(soup, "Fuel tank capacity:")
            length = get_spec_detail(soup, "Exterior length:")
            width = get_spec_detail(soup, "Exterior body width:")
            height = get_spec_detail(soup, "Exterior height:")
            wheelbase = get_spec_detail(soup, "Wheelbase:")
            curbWeight = get_spec_detail(soup, "Curb weight:")
            cargoCapacity = get_spec_detail(soup, "Interior maximum rear cargo volume:")

            # --- Parse trim from title ---
            trim = car["model"].replace(car["make"], "").strip()
            
            
            options = {
                "trim": trim,
                "bodyStyle": spec_map.get("bodySeating", "Unknown").split("/")[0],
                "doors": "4",
                "engine": spec_map.get("engine", "Unknown"),
                "engineSize": engineSize,
                "cylinders": "4",
                "valves": "16",
                "horsepower": horsepower,
                "torque": torque,
                "compression": "10.6:1",
                "fuelSystem": "Direct Injection",
                "transmission": spec_map.get("transmission", "Unknown"),
                "drivetrain": spec_map.get("drivetrain", "Unknown"),
                "fuelType": "Regular Unleaded",
                "fuelCapacity": fuelCapacity,
                "mpgCity": mpgCity,
                "mpgHighway": mpgHighway,
                "emissionRating": "ULEV-3",
                "seatingCapacity": spec_map.get("bodySeating", "Unknown").split("/")[-1].split()[0],
                "cargoCapacity": cargoCapacity,
                "wheelbase": wheelbase,
                "length": length,
                "width": width,
                "height": height,
                "curbWeight": curbWeight,
                "groundClearance": "5.1 in",
                "warrantyBasic": "3 years/36,000 miles",
                "warrantyPowertrain": "5 years/60,000 miles",
                "warrantyRoadside": "3 years/36,000 miles",
                "buildLocation": "Marysville, OH",
                "countryOfOrigin": "USA",
                "safetyFeatures": ["Lane departure", "Security system"],
                "techFeatures": tech,
                "interiorFeatures": interior,
                "exteriorFeatures": exterior,
                "performanceFeatures": performance,
                "standardEquipment": standard,
                "optionalEquipment": optional
            }

            color = spec_map.get("exteriorColor", "Unknown")
            enriched.append({**car, "color": color, "options": options})

        except Exception as e:
            enriched.append({**car, "options": {}, "error": str(e)})
            continue
        
    driver.quit()
    
    with open("final_car_data.json", "w") as f:
        json.dump(enriched, f, indent=2)

    pd.DataFrame(enriched).to_csv("final_car_data.csv", index=False)
    # print("✅ Data saved to final_car_data.json and final_car_data.csv")
    # return enriched
    return {"vehicles": "All car details extracted and saved."}


@app.get("/cars")
def get_cars():
    
    car_list =  get_all_car_listings()
    detailed_data =  extract_car_details(car_list)  
    
    return JSONResponse(content={"vehicles": detailed_data})


@app.get("/car_detailed_inventory")
def car_detailed():
    file_path = "final_car_data.json"  # Path to your JSON file
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
        # return data
        return JSONResponse(content={"vehicles": data}, status_code=200)
    return JSONResponse(content={"error": "File not found"}, status_code=404)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 
    
    
    

    # car_list = get_all_car_listings()
    # detailed_data = extract_car_details(car_list)
    

    # with open("final_car_data.json", "w") as f:
    #     json.dump(detailed_data, f, indent=2)

    # pd.DataFrame(detailed_data).to_csv("final_car_data.csv", index=False)
    # print("✅ Data saved to final_car_data.json and final_car_data.csv")
