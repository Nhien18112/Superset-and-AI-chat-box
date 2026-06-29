package com.vdt.dataplatform.service;

import com.vdt.dataplatform.model.ChatMessage;
import com.vdt.dataplatform.model.ChatSession;
import com.vdt.dataplatform.repository.ChatMessageRepository;
import com.vdt.dataplatform.repository.ChatSessionRepository;
import com.vdt.dataplatform.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

@Service
public class ChatService {

    @Autowired
    private ChatSessionRepository chatSessionRepository;

    @Autowired
    private ChatMessageRepository chatMessageRepository;

    @Autowired
    private UserRepository userRepository;

    @Value("${superset.automation-worker-url:http://python-worker:8000}")
    private String pythonWorkerUrl;

    @Value("${python-worker.internal-api-key}")
    private String internalApiKey;

    private static final Logger logger = LoggerFactory.getLogger(ChatService.class);

    private final RestTemplate restTemplate = buildRestTemplate();

    private static RestTemplate buildRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(10_000);
        factory.setReadTimeout(45_000);
        return new RestTemplate(factory);
    }

    public String processChat(String sessionId, String query, String username) {
        // Security check
        Optional<ChatSession> sessionOpt = chatSessionRepository.findById(sessionId);
        if (sessionOpt.isPresent()) {
            if (!sessionOpt.get().getUsername().equals(username)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Access Denied: Session belongs to another user.");
            }
        } else {
            ChatSession newSession = new ChatSession();
            newSession.setSessionId(sessionId);
            newSession.setUsername(username);
            chatSessionRepository.save(newSession);
        }

        // Fetch history
        List<ChatMessage> history = chatMessageRepository.findBySessionIdOrderByCreatedAtAsc(sessionId);

        // Map history for Python MCP payload
        List<Map<String, Object>> formattedHistory = new ArrayList<>();
        for (ChatMessage msg : history) {
            Map<String, Object> hm = new HashMap<>();
            hm.put("text", msg.getContent());
            hm.put("isUser", "USER".equals(msg.getSenderType()));
            formattedHistory.add(hm);
        }

        // Save incoming user message
        ChatMessage userMsg = new ChatMessage();
        userMsg.setSessionId(sessionId);
        userMsg.setSenderType("USER");
        userMsg.setContent(query);
        chatMessageRepository.save(userMsg);

        // Look up user role from DB so the Python Worker can apply correct RLS
        String role = userRepository.findByUsername(username)
                .map(com.vdt.dataplatform.model.User::getRole)
                .orElse("");

        // Build payload
        Map<String, Object> payload = new HashMap<>();
        payload.put("query", query);
        payload.put("username", username);
        payload.put("role", role);
        payload.put("history", formattedHistory);

        // Authenticate the internal call with the shared API key
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Internal-Api-Key", internalApiKey);
        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);

        String aiResponse = "Error connecting to AI Agent.";
        try {
            Map<String, Object> response = restTemplate.postForObject(
                    pythonWorkerUrl + "/api/chat", request, Map.class);
            if (response != null && response.containsKey("reply")) {
                aiResponse = (String) response.get("reply");
            }
        } catch (ResourceAccessException e) {
            logger.warn("AI agent timed out or was unreachable: {}", e.getMessage());
            aiResponse = "The AI agent is taking too long to respond. Please try a simpler query or try again shortly.";
        } catch (Exception e) {
            logger.error("Unexpected error calling Python Worker: {}", e.getMessage());
            aiResponse = "Error from Python Worker: " + e.getMessage();
        }

        // Save AI response
        ChatMessage aiMsg = new ChatMessage();
        aiMsg.setSessionId(sessionId);
        aiMsg.setSenderType("AI");
        aiMsg.setContent(aiResponse);
        chatMessageRepository.save(aiMsg);

        return aiResponse;
    }
}
