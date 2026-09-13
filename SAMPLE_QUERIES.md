# Sample Queries for FinGraphRAG

## Your Data Overview
Your CSV files contain information about:
- **Indian companies** and their **Chinese partnerships**
- **Industries**: EV Batteries, Automotive, Consumer Electronics, Construction Equipment, IT Services
- **Companies**: Reliance Industries, Adani Group, JSW Group, Tata Motors, Bharti Enterprises, etc.
- **Chinese Partners**: CATL, BYD, Chery, AESC, Haier, SAIC, etc.

## Sample Queries to Test

### Basic Fact-Finding Queries
1. **"What companies have partnerships with CATL?"**
   - Expected: Should return Reliance Industries and Adani Group

2. **"Which Indian companies are in the EV manufacturing sector?"**
   - Expected: Should return Adani Group, JSW Group, Tata Motors, SAIC Motor India

3. **"What is the relationship between JSW Group and Chery Automobile?"**
   - Expected: Technology Licensing deal for new-energy venture

4. **"What deals are currently under discussion?"**
   - Expected: Should list deals with "Under Discussion" status

### Relationship-Based Queries
5. **"How are Tata Group and Chinese companies connected?"**
   - Expected: Should show connections with AESC Apollo and Chery Automobile

6. **"What is the partnership structure between Bharti Enterprises and Haier?"**
   - Expected: 49% JV where Bharti + Warburg Pincus acquire 49% stake

7. **"Which companies have multiple Chinese partners?"**
   - Expected: Adani Group (BYD, CATL), Tata Group (AESC, Chery)

### Industry-Specific Queries
8. **"What is the risk exposure for companies in the EV ecosystem?"**
   - Expected: Should show High/Moderate risk levels for EV companies

9. **"Which companies are in the consumer electronics sector?"**
   - Expected: Bharti Enterprises, Haier India

10. **"What construction equipment companies have Chinese presence?"**
    - Expected: Sany Heavy Industry

### Financial/Investment Queries
11. **"What investments have been made in battery technology?"**
    - Expected: Tata Group £40M+ for AESC technology, Reliance evaluating investments

12. **"What are the revenue figures for Sany Heavy Industry?"**
    - Expected: FY24 revenue ₹6,151 Cr, profit ₹340 Cr

### Status-Based Queries
13. **"Which deals have been confirmed?"**
    - Expected: Should list all deals with "Confirmed" status

14. **"What deals are pending clearance?"**
    - Expected: Should show deals awaiting security clearance

### Comparative Queries
15. **"Compare the Chinese partnerships of Adani Group vs JSW Group"**
    - Expected: Should show different partners and deal types

16. **"Which sector has the highest Chinese presence?"**
    - Expected: Likely EV_Ecosystem or Consumer_Durables

## Expected Answers (Based on Your Data)

### Query 1: "What companies have partnerships with CATL?"
**Expected Answer**: Based on the data, Reliance Industries has a Technology Partnership with CATL for evaluating investment in Chinese-origin battery technology firms. Adani Group also has discussions with CATL for partnership in the EV battery sector.

### Query 2: "Which Indian companies are in the EV manufacturing sector?"
**Expected Answer**: The data shows several Indian companies in EV manufacturing: Adani Group (with BYD talks), JSW Group (with Chery deal), Tata Motors (with AESC JV and Chery platform licensing), and SAIC Motor India (with SAIC JV).

### Query 3: "What is the relationship between JSW Group and Chery Automobile?"
**Expected Answer**: JSW Group has a Technology Licensing deal with Chery Automobile. They signed a deal to source technology and components for their new-energy venture. Additionally, JSW has discussions with SAIC Motor to increase stake in JSW MG Motor India.

### Query 4: "What deals are currently under discussion?"
**Expected Answer**: Several deals are under discussion: Reliance Industries evaluating investment in CATL, Adani Group talks with BYD for EV sector foray and discussions with CATL, and JSW Group talks to increase stake in JSW MG Motor India with SAIC Motor.

## Testing Commands

### Test via CLI
```powershell
python -m src.main ask "What companies have partnerships with CATL?"
python -m src.main ask "Which Indian companies are in the EV manufacturing sector?"
python -m src.main ask "What is the relationship between JSW Group and Chery Automobile?"
```

### Test via Streamlit UI
1. Open http://localhost:8501
2. Enter any of the above queries in the text area
3. Click "🚀 Submit Query"
4. Review the answer and sources

### Test via API
```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/query `
  -ContentType "application/json" `
  -Body '{"query":"What companies have partnerships with CATL?","session_id":"test"}'
```

## Troubleshooting Neo4j Connection

If you're getting generic responses, the Neo4j connection might be failing. Check:

1. **Neo4j URI**: Ensure it's accessible (currently set to neo4j://5a76f90e.databases.neo4j.io)
2. **Credentials**: Verify username and password in .env file
3. **Network**: Check if you can reach the Neo4j instance
4. **SSL**: The system was modified to handle SSL certificate issues

### Quick Fix for Neo4j
The current configuration uses `neo4j://` scheme to bypass SSL issues. If this doesn't work, you may need to:
1. Check your Neo4j instance is running
2. Verify credentials are correct
3. Check network connectivity

## Data Summary
- **Total Companies**: 108 unique companies across 3 CSV files
- **Industries**: EV Batteries, Automotive, Consumer Electronics, Construction Equipment, IT Services
- **Relationship Types**: Technology Partnership, JV, Technology Licensing, Platform Licensing, etc.
- **Status Types**: Confirmed, Under Discussion, Active, Pending Clearance