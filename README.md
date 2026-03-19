# RouteWise

RouteWise is an intelligent route-planning system for cross-border logistics between China and Kenya.

It helps users determine the most efficient shipping route based on cost, delivery time, and transport mode using graph-based algorithms such as Dijkstra and A*.

---

## 🚀 Core Features

- Intelligent route optimization (Dijkstra & A*)
- Cost vs Time preference control
- Multi-modal logistics (Sea, Air, Rail, Road)
- Two-way routing (China ↔ Kenya)
- Route comparison (Fastest vs Cheapest vs Balanced)
- Step-by-step route breakdown
- Logistics hub knowledge base
- Clean, modern web interface

---

## 🧠 How It Works

The system models logistics as a graph:

- Nodes → ports, cities, logistics hubs  
- Edges → transport routes with cost and time  

Algorithms compute the optimal route based on user preferences.

---

## 🛠️ Tech Stack

Backend:
- Python
- Flask

Frontend:
- Jinja Templates
- HTML
- JavaScript
- Tailwind CSS

Data:
- JSON (initial)
- SQLite (optional)

Algorithms:
- Dijkstra
- A* (optional extension)

---

## 📦 Project Structure
RouteWise/
├── app.py
├── backend/
│ ├── route_engine/
│ ├── data_loader.py
│ ├── models.py
│
├── templates/
├── static/
│ ├── css/
│ ├── js/
│
├── data/
├── docs/
├── README.md


---

## 🎯 Project Goal

To build a practical and intelligent system that simplifies logistics decision-making for cross-border e-commerce between China and Kenya.

---

## 📌 Status

🚧 In Development (Graduation Project)
