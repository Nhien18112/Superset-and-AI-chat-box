package com.vdt.dataplatform.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
public class SupersetService {

    private static final Logger logger = LoggerFactory.getLogger(SupersetService.class);

    @Value("${superset.url}")
    private String supersetUrl;

    @Value("${superset.username}")
    private String supersetUsername;

    @Value("${superset.password}")
    private String supersetPassword;

    @Value("${superset.automation-worker-url}")
    private String automationWorkerUrl;

    private String cachedDashboardUuid = null;

    private final RestTemplate restTemplate = new RestTemplate();

    public String getAdminAccessToken() {
        String loginUrl = supersetUrl + "/api/v1/security/login";
        
        Map<String, String> loginRequest = new HashMap<>();
        loginRequest.put("username", supersetUsername);
        loginRequest.put("password", supersetPassword);
        loginRequest.put("provider", "db");
        loginRequest.put("refresh", "true");

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        HttpEntity<Map<String, String>> request = new HttpEntity<>(loginRequest, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(loginUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                return (String) response.getBody().get("access_token");
            }
        } catch (Exception e) {
            logger.error("Failed to authenticate with Superset admin: {}", e.getMessage());
            throw new RuntimeException("Superset admin authentication failed");
        }
        throw new RuntimeException("Superset admin authentication failed (no token)");
    }

    public synchronized String getDashboardUuid() {
        if (cachedDashboardUuid != null) {
            return cachedDashboardUuid;
        }

        String createDashboardUrl = automationWorkerUrl + "/api/create-dashboard";
        Map<String, Object> payload = new HashMap<>();
        payload.put("dataset_id", 1);
        payload.put("dashboard_title", "Automated Market Overview");

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(createDashboardUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                cachedDashboardUuid = (String) response.getBody().get("dashboard_uuid");
                logger.info("Successfully fetched embedded dashboard UUID from worker: {}", cachedDashboardUuid);
                return cachedDashboardUuid;
            }
        } catch (Exception e) {
            logger.error("Failed to trigger dashboard creation via worker: {}", e.getMessage());
            throw new RuntimeException("Dashboard creation failed", e);
        }
        throw new RuntimeException("Failed to retrieve dashboard UUID from worker");
    }

    public String getGuestToken(String targetUsername) {
        String adminToken = getAdminAccessToken();
        String guestTokenUrl = supersetUrl + "/api/v1/security/guest_token/";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(adminToken);

        Map<String, Object> payload = new HashMap<>();
        
        // Ensure the payload matches the expected embedded SDK guest token structure
        Map<String, String> userMap = new HashMap<>();
        userMap.put("username", targetUsername);
        userMap.put("first_name", targetUsername);
        userMap.put("last_name", "User");
        payload.put("user", userMap);

        List<Map<String, String>> resources = new ArrayList<>();
        Map<String, String> resource = new HashMap<>();
        resource.put("type", "dashboard");
        resource.put("id", getDashboardUuid());
        resources.add(resource);
        payload.put("resources", resources);

        // Add RLS configuration if necessary, depending on the implementation details.
        // For Superset Embedded, RLS rules can be passed in the token itself if the feature flag is enabled.
        List<Map<String, Object>> rls = new ArrayList<>();
        // In this implementation, we simply specify an RLS filter rule based on the username
        // So that the frontend embedded iframe only shows data for this specific user.
        // This prevents the user from modifying the frontend code to see other people's data.
        // We'll leave the actual clause blank or generic unless a specific schema requires it.
        // The instructions state: The Guest Token payload MUST securely embed the extracted User ID
        Map<String, Object> rlsRule = new HashMap<>();
        rlsRule.put("clause", "user_id = '" + targetUsername + "'");
        rls.add(rlsRule);
        payload.put("rls", rls); 

        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(guestTokenUrl, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                return (String) response.getBody().get("token");
            }
        } catch (Exception e) {
            logger.error("Failed to fetch guest token from Superset: {}", e.getMessage());
            throw new RuntimeException("Failed to fetch guest token");
        }
        throw new RuntimeException("Failed to fetch guest token (no token in response)");
    }
}
