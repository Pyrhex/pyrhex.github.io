# Google Calendar Schedule Uploader

This script (`google_cal.py`) automates the process of uploading work schedules from an Excel file to Google Calendar for a list of employees. It handles concurrency, duplicate checking, and error recovery for API rate limits.

---

## 🧠 Background

The script started as a **serial implementation**, processing one person’s schedule at a time. While functional for small data, it quickly **timed out** when uploading more than 4 schedules due to the sequential Google Calendar API calls.

---

## ⚙️ Evolution of the Solution

### 🔁 1. Initial Serial Version

- Simple but slow.
- **Timeouts occurred** with more than 4 names due to API delays.

### 🧵 2. Naive Multithreaded Upload

- Introduced multithreading using `ThreadPoolExecutor` with **5 workers**.
- Resulted in **race conditions** where two threads would check for duplicates simultaneously and both upload the same event.
# Google Calendar Schedule Uploader

This script (`google_cal.py`) automates the process of uploading work schedules from an Excel file to Google Calendar for a list of employees. It handles concurrency, duplicate checking, and error recovery for API rate limits.

---

## 🧠 Background

The script started as a **serial implementation**, processing one person’s schedule at a time. While functional for small data, it quickly **timed out** when uploading more than 4 schedules due to the sequential Google Calendar API calls.

---

## ⚙️ Evolution of the Solution

### 🔁 1. Initial Serial Version

- Simple but slow.
- **Timeouts occurred** with more than 4 names due to API delays.

### 🧵 2. Naive Multithreaded Upload

- Introduced multithreading using `ThreadPoolExecutor` with **5 workers**.
- Resulted in **race conditions** where two threads would check for duplicates simultaneously and both upload the same event.

### 🔒 3. Lock-Based Concurrency

- Used **threading locks** to guard critical sections.
- Prevented race conditions, but **reintroduced the serial bottleneck** due to lock contention.

### 👤 4. Thread-Per-Name Isolation

- Designed each thread to process **only one name at a time**, with max 5 concurrent threads.
- Prevented overlapping event uploads and **eliminated race conditions** entirely.
- ✅ Fast and safe parallelism.

### 🔁 5. Retry Mechanism for Rate Limits

- Google Calendar API still occasionally returned **403/429 errors**.
- Implemented a **retry system**:
  - Retries up to **3 times** with **exponential backoff** (2s, 4s, 8s).
  - Avoids crashing on transient issues.
- ✅ Significantly more reliable under API pressure.

---

## 🗂️ How It Works

1. Reads `schedule.xlsx`, parses shift times for each name.
2. Converts times to timezone-aware datetime objects.
3. Creates one upload task per name.
4. Uses `ThreadPoolExecutor(max_workers=5)` to upload concurrently.
5. Checks existing events to avoid duplicates.
6. Retries failed uploads due to rate limiting (up to 3 times).

---

## 🔧 Requirements

- Google Cloud service account with Calendar API enabled
- Credentials JSON file path configured in code
- Python 3.8+
- Python dependencies:
  ```bash
  pip install pandas openpyxl google-api-python-client google-auth pytz
### 🔒 3. Lock-Based Concurrency

- Used **threading locks** to guard critical sections.
- Prevented race conditions, but **reintroduced the serial bottleneck** due to lock contention.

### 👤 4. Thread-Per-Name Isolation

- Designed each thread to process **only one name at a time**, with max 5 concurrent threads.
- Prevented overlapping event uploads and **eliminated race conditions** entirely.
- ✅ Fast and safe parallelism.

### 🔁 5. Retry Mechanism for Rate Limits

- Google Calendar API still occasionally returned **403/429 errors**.
- Implemented a **retry system**:
  - Retries up to **3 times** with **exponential backoff** (2s, 4s, 8s).
  - Avoids crashing on transient issues.
- ✅ Significantly more reliable under API pressure.

---

## 🗂️ How It Works

1. Reads `schedule.xlsx`, parses shift times for each name.
2. Converts times to timezone-aware datetime objects.
3. Creates one upload task per name.
4. Uses `ThreadPoolExecutor(max_workers=5)` to upload concurrently.
5. Checks existing events to avoid duplicates.
6. Retries failed uploads due to rate limiting (up to 3 times).

---

## 🔧 Requirements

- Google Cloud service account with Calendar API enabled
- Credentials JSON file path configured in code
- Python 3.8+
- Python dependencies:
  ```bash
  pip install pandas openpyxl google-api-python-client google-auth pytz