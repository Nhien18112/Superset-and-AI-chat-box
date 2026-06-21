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

    @Autowired
    private com.vdt.dataplatform.repository.UserRepository userRepository;

    @GetMapping("/sso-login")
    public ResponseEntity<?> getSsoToken() {
        Object principal = SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        String username;
        
        if (principal instanceof UserDetails) {
            UserDetails userDetails = (UserDetails) principal;
            username = userDetails.getUsername();
        } else {
            username = principal.toString();
        }

        String role = "";
        com.vdt.dataplatform.model.User dbUser = userRepository.findByUsername(username).orElse(null);
        if (dbUser != null) {
            role = dbUser.getRole();
        }

        try {
            String ssoToken = supersetService.getSsoToken(username, role);
            Map<String, String> response = new HashMap<>();
            response.put("token", ssoToken);
            response.put("dashboardId", supersetService.getDashboardUuid());
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.internalServerError().body("Error fetching SSO token: " + e.getMessage());
        }
    }
}
