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
    private Integer cachedDatasetId = null;

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
                cachedDatasetId = (Integer) response.getBody().get("dataset_id");
                logger.info("Successfully fetched embedded dashboard UUID from worker: {}", cachedDashboardUuid);
                return cachedDashboardUuid;
            }
        } catch (Exception e) {
            logger.error("Failed to trigger dashboard creation via worker: {}", e.getMessage());
            throw new RuntimeException("Dashboard creation failed", e);
        }
        throw new RuntimeException("Failed to retrieve dashboard UUID from worker");
    }

    @Value("${superset.secret-key}")
    private String supersetSecretKey;

    public String getSsoToken(String targetUsername, String role) {
        // We use the same secret as Superset to generate the JWT

        // Create JWT token for custom Superset login
        long nowMillis = System.currentTimeMillis();
        Date now = new Date(nowMillis);
        long expMillis = nowMillis + 3600000; // 1 hour expiration
        Date exp = new Date(expMillis);

        io.jsonwebtoken.JwtBuilder builder = io.jsonwebtoken.Jwts.builder()
                .setSubject(targetUsername)
                .claim("username", targetUsername)
                .claim("role", role)
                .setIssuedAt(now)
                .setExpiration(exp)
                .signWith(io.jsonwebtoken.security.Keys.hmacShaKeyFor(supersetSecretKey.getBytes()));

        return builder.compact();
    }
}
