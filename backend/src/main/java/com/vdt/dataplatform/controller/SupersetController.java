package com.vdt.dataplatform.controller;

import com.vdt.dataplatform.service.SupersetService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/superset")
public class SupersetController {

    @Autowired
    private SupersetService supersetService;

    @GetMapping("/guest-token")
    public ResponseEntity<?> getGuestToken() {
        Object principal = SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        String username;
        
        if (principal instanceof UserDetails) {
            username = ((UserDetails) principal).getUsername();
        } else {
            username = principal.toString();
        }

        try {
            String guestToken = supersetService.getGuestToken(username);
            Map<String, String> response = new HashMap<>();
            response.put("token", guestToken);
            response.put("dashboardId", supersetService.getDashboardUuid());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body("Error fetching guest token: " + e.getMessage());
        }
    }
}
