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
public class CodexService {

    private static final Logger logger = LoggerFactory.getLogger(CodexService.class);

    @Value("${codex.api.url}")
    private String codexApiUrl;

    @Value("${codex.api.key}")
    private String codexApiKey;

    private final RestTemplate restTemplate = new RestTemplate();

    public String processUserQuery(String userQuery, String targetUsername) {
        String systemPrompt = "You are an expert SQL assistant for a mock stock platform. "
                + "Generate a generic PostgreSQL query based on the user's question. "
                + "The database schema is:\n"
                + "- dim_tickers (ticker_id, company_name, industry)\n"
                + "- dim_brokers (broker_id, broker_name)\n"
                + "- dim_investors (investor_id, investor_name, broker_id)\n"
                + "- fact_orders (order_id, investor_id, ticker_id, order_date, order_type, volume, price, status)\n"
                + "IMPORTANT: Do NOT add WHERE clauses for the user ID. Row-Level Security is handled automatically by Superset. "
                + "Return ONLY the SQL query.";

        String generatedSql = callCodexApi(systemPrompt, userQuery);
        return executeSqlInSupersetContext(generatedSql, targetUsername);
    }

    private String callCodexApi(String systemPrompt, String userQuery) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(codexApiKey);

        Map<String, Object> payload = new HashMap<>();
        payload.put("model", "gpt-3.5-turbo"); // Placeholder for Codex-compatible model
        
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
            ResponseEntity<Map> response = restTemplate.postForEntity(codexApiUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> message = (Map<String, Object>) choices.get(0).get("message");
                    return (String) message.get("content");
                }
            }
        } catch (Exception e) {
            logger.error("Codex API error in callCodexApi: {}", e.getMessage());
            return "Failed to generate query: " + e.getMessage();
        }
        return "Error: Empty response from Codex.";
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
        headers.setBearerAuth(codexApiKey);

        Map<String, Object> payload = new HashMap<>();
        payload.put("model", "gpt-3.5-turbo"); 
        
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
            ResponseEntity<Map> response = restTemplate.postForEntity(codexApiUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                List<Map<String, Object>> choices = (List<Map<String, Object>>) response.getBody().get("choices");
                if (choices != null && !choices.isEmpty()) {
                    Map<String, Object> message = (Map<String, Object>) choices.get(0).get("message");
                    generatedSql = (String) message.get("content");
                }
            } else {
                return "Error: Empty response from Codex.";
            }
        } catch (Exception e) {
            logger.error("Codex API error: {}", e.getMessage());
            return "Failed to generate query: " + e.getMessage();
        }

        return executeSqlInSupersetContext(generatedSql, targetUsername);
    }

    private String executeSqlInSupersetContext(String sql, String username) {
        logger.info("Proxying MCP SQL execution to Superset for user: {}", username);
        logger.info("Executing SQL: {}", sql);
        
        return "Executed SQL securely for user " + username + ":\n\n" + sql + "\n\n(Mocked ResultSet: 10 rows retrieved)";
    }
}
