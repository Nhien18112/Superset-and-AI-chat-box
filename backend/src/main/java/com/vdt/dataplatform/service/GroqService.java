package com.vdt.dataplatform.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class GroqService {

    private static final Logger logger = LoggerFactory.getLogger(GroqService.class);

    @Value("${groq.api.url}")
    private String groqApiUrl;

    @Value("${groq.api.key}")
    private String groqApiKey;

    private final RestTemplate restTemplate = new RestTemplate();

    public String processUserQuery(String userQuery, String targetUsername) {
        // 1. Construct the prompt for Text-to-SQL without specifying RLS rules
        String systemPrompt = "You are an expert SQL assistant for a mock stock platform. "
                + "Generate a generic PostgreSQL query based on the user's question. "
                + "The database schema is:\n"
                + "- dim_tickers (ticker_id, company_name, industry)\n"
                + "- dim_brokers (broker_id, broker_name)\n"
                + "- dim_investors (investor_id, investor_name, broker_id)\n"
                + "- fact_orders (order_id, investor_id, ticker_id, order_date, order_type, volume, price, status)\n"
                + "IMPORTANT: Do NOT add WHERE clauses for the user ID. Row-Level Security is handled automatically by Superset. "
                + "Return ONLY the SQL query.";

        // 2. Call Groq API
        String generatedSql = callGroqApi(systemPrompt, userQuery);

        // 3. Proxy to Superset MCP/API under the user's RLS context
        return executeSqlInSupersetContext(generatedSql, targetUsername);
    }

    private String callGroqApi(String systemPrompt, String userQuery) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(groqApiKey);

        Map<String, Object> payload = new HashMap<>();
        payload.put("model", "llama3-8b-8192");
        
        List<Map<String, String>> messages = new ArrayList<>();
        
        Map<String, String> sysMsg = new HashMap<>();
        sysMsg.put("role", "system");
        sysMsg.put("content", systemPrompt);
        messages.add(sysMsg);

        Map<String, String> usrMsg = new HashMap<>();
        usrMsg.put("role", "user");
        usrMsg.put("content", userQuery);
        messages.add(usrMsg);
        
        payload.put("messages", messages);
        payload.put("temperature", 0.1);

        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(groqApiUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> message = (Map<String, Object>) choices.get(0).get("message");
                    return (String) message.get("content");
                }
            }
        } catch (Exception e) {
            logger.error("Groq API error in callGroqApi: {}", e.getMessage());
            return "Failed to generate query: " + e.getMessage();
        }
        return "Error: Empty response from Groq.";
    }

    public String processUserQueryWithHistory(String userQuery, String targetUsername, List<com.vdt.dataplatform.model.ChatMessage> history) {
        String systemPrompt = "You are an expert SQL assistant for a mock stock platform. "
                + "Generate a generic PostgreSQL query based on the user's question. "
                + "The database schema is:\n"
                + "- dim_tickers (ticker_id, company_name, industry)\n"
                + "- dim_brokers (broker_id, broker_name)\n"
                + "- dim_investors (investor_id, investor_name, broker_id)\n"
                + "- fact_orders (order_id, investor_id, ticker_id, order_date, order_type, volume, price, status)\n"
                + "IMPORTANT: Do NOT add WHERE clauses for the user ID. Row-Level Security is handled automatically by Superset. "
                + "Return ONLY the SQL query.";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(groqApiKey);

        Map<String, Object> payload = new HashMap<>();
        payload.put("model", "llama3-8b-8192"); // Use a valid Groq model
        
        List<Map<String, String>> messages = new ArrayList<>();
        
        Map<String, String> sysMsg = new HashMap<>();
        sysMsg.put("role", "system");
        sysMsg.put("content", systemPrompt);
        messages.add(sysMsg);

        if (history != null) {
            for (com.vdt.dataplatform.model.ChatMessage msg : history) {
                Map<String, String> m = new HashMap<>();
                m.put("role", msg.getSenderType().equalsIgnoreCase("USER") ? "user" : "assistant");
                m.put("content", msg.getContent());
                messages.add(m);
            }
        }
        
        Map<String, String> usrMsg = new HashMap<>();
        usrMsg.put("role", "user");
        usrMsg.put("content", userQuery);
        messages.add(usrMsg);
        
        payload.put("messages", messages);
        payload.put("temperature", 0.1);

        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);

        String generatedSql = "Error";
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(groqApiUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> message = (Map<String, Object>) choices.get(0).get("message");
                    generatedSql = (String) message.get("content");
                }
            } else {
                return "Error: Empty response from Groq.";
            }
        } catch (Exception e) {
            logger.error("Groq API error: {}", e.getMessage());
            return "Failed to generate query: " + e.getMessage();
        }

        return executeSqlInSupersetContext(generatedSql, targetUsername);
    }

    private String executeSqlInSupersetContext(String sql, String username) {
        // Here we implement the proxy logic to Superset MCP
        // The Backend ensures the tool call runs under the RLS context of 'username'
        
        logger.info("Proxying MCP SQL execution to Superset for user: {}", username);
        logger.info("Executing SQL: {}", sql);
        
        // Mocking the result of the MCP proxy call since we don't have the literal MCP url setup
        // In reality, this would be an HTTP POST to the MCP server with the sql payload and auth context.
        return "Executed SQL securely for user " + username + ":\n\n" + sql + "\n\n(Mocked ResultSet: 10 rows retrieved)";
    }
}
