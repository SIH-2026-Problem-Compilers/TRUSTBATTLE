**TRUSTBATTLE — Team Work Distribution**

Our project flow is:

**Sensor Data → Analysis → Evidence → Trust Score → Trust-Aware Fusion → Dashboard**

The work is divided so that everyone builds one important part, and all parts finally connect together.

---

### 👨‍💻 Member 1 — AI/ML: Physical & Sensor Analysis

**Work:**

* Work with GNSS + IMU data
* Extract position, velocity, acceleration, heading, etc.
* Check whether sensor readings are physically consistent
* Detect abnormal trajectory/movement
* Build the first anomaly-detection model

**Why?**
A spoofed or faulty sensor may report values that look normal individually but don't match the actual movement. This module finds those physical inconsistencies.

**Output:**
`Physical Consistency Score + Anomaly Score`

---

### 👨‍💻 Member 2 — AI/ML: Temporal & Telemetry Analysis

**Work:**

* Analyze sensor data over time
* Detect replay/stale data
* Analyze timestamp and sequence behaviour
* Analyze telemetry/network features such as packet delay, packet loss and packet rate
* Build anomaly detection for unusual temporal/network behaviour

**Why?**
Manipulated or replayed information can have abnormal timing or communication patterns even when the actual sensor values look valid.

**Output:**
`Temporal Anomaly Score + Network Anomaly Score`

---

### 👨‍💻 Member 3 — AI/ML: Trust Engine & Sensor Fusion

**Work:**

* Collect outputs from Member 1, Member 2 and Cybersecurity member
* Combine physical, temporal, cyber and cross-sensor evidence
* Build the **Observation Trust Score (0–100)**
* Implement dynamic trust: trust should decrease during anomalies and recover when behaviour becomes normal
* Build trust-aware sensor fusion
* Compare normal fusion vs trust-aware fusion

**Why?**
This is the core of TRUSTBATTLE. We don't just want to detect an anomaly; we want to determine **how much we should trust that particular observation right now** and reduce its influence if necessary.

**Output:**
`Observation Trust Score + Sensor Weights + Final State Estimate`

---

### 🛡️ Member 4 — Cybersecurity: Threat & Attack Simulation

**Work:**

* Understand the threat scenarios
* Create controlled simulations for:

  * GNSS spoofing
  * Replay/stale data
  * Manipulated telemetry
  * Network anomalies
  * Sensor malfunction
  * Conflicting sensor information
* Generate attack/failure datasets with known ground truth
* Test whether our system detects these scenarios correctly
* Maintain the threat model and security documentation

**Why?**
The AI models need realistic abnormal situations to learn/test against. We need controlled scenarios where we know exactly what was manipulated so that we can measure detection performance.

**Output:**
`Attack/Failure Scenarios + Synthetic Data + Ground Truth`

**Important:** Everything will be done using public datasets and controlled simulation/lab environments.

---

### 💻 Member 5 — Software: Backend & Dashboard

**Work:**

* Build FastAPI backend
* Create APIs for sensor data, trust scores and alerts
* Connect AI models with the backend
* Create database
* Implement real-time data flow
* Build React dashboard
* Add map, sensor status, trust scores, alerts and evidence explanation

**Why?**
The AI results need to be presented in a simple way to the operator. The dashboard will show **what is happening, which observation is suspicious, how much it is trusted, and why**.

**Output:**
`Working Web Application + Real-Time Dashboard`

---

## 🔗 How everyone's work connects

```text
              SENSOR DATA
                   ↓
          ┌─────────────────┐
          │ Data Processing │
          └────────┬────────┘
                   ↓
       ┌───────────┼───────────┐
       ↓           ↓           ↓
   Member 1     Member 2    Member 4
   Physical     Temporal     Cyber
   Analysis     Analysis     Scenarios
       │           │           │
       └───────────┼───────────┘
                   ↓
              Member 3
           TRUST ENGINE
                   ↓
            Trust Score
                   ↓
          Trust-Aware Fusion
                   ↓
              Member 5
          Backend + Dashboard
                   ↓
              FINAL DEMO
```

## 🎯 Final demo flow

```text
Normal sensor data
       ↓
All sources trusted
       ↓
Simulated GNSS spoofing
       ↓
GNSS starts disagreeing with IMU/other evidence
       ↓
Anomaly detected
       ↓
Trust score decreases
       ↓
GNSS influence is reduced
       ↓
Reliable sources get more influence
       ↓
Dashboard explains WHY
       ↓
GNSS becomes normal again
       ↓
Trust gradually recovers
```

### One important rule

**Don't work as five separate projects.** Every member should regularly provide their output/API/data format to the next module so that integration happens from the beginning, not at the end.

Our final goal is not simply **"detect a hacked sensor."**

It is:

**"Determine whether a particular observation can be trusted right now, explain why, and prevent unreliable information from unnecessarily affecting the final battlefield picture."**