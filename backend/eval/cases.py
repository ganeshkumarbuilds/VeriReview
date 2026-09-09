# Each case has a diff and a label: "buggy" (should trigger a finding) or "clean" (should not)

TEST_CASES = [
    {
        "id": "n_plus_one",
        "label": "buggy",
        "diff": """
public List<Order> getOrdersForUser(User user) {
    List<Order> orders = new ArrayList<>();
    for (Long id : user.getOrderIds()) {
        orders.add(orderRepository.findById(id).orElse(null));
    }
    return orders;
}
"""
    },
    {
        "id": "private_transactional",
        "label": "buggy",
        "diff": """
@Transactional
private void updateBalance(Account account, double amount) {
    account.setBalance(account.getBalance() + amount);
    accountRepository.save(account);
}
"""
    },
    {
        "id": "sql_injection",
        "label": "buggy",
        "diff": """
public List<User> searchUsers(String name) {
    String query = "SELECT * FROM users WHERE name = '" + name + "'";
    return jdbcTemplate.query(query, new UserRowMapper());
}
"""
    },
    {
        "id": "hardcoded_secret",
        "label": "buggy",
        "diff": """
public class JwtUtil {
    private static final String SECRET_KEY = "my-super-secret-key-12345";

    public String generateToken(String username) {
        return Jwts.builder().setSubject(username).signWith(SignatureAlgorithm.HS256, SECRET_KEY).compact();
    }
}
"""
    },
    {
        "id": "unbounded_findall",
        "label": "buggy",
        "diff": """
@GetMapping("/users")
public List<User> getAllUsers() {
    return userRepository.findAll();
}
"""
    },
    {
        "id": "clean_paginated_query",
        "label": "clean",
        "diff": """
@GetMapping("/users")
public Page<User> getUsers(@RequestParam int page, @RequestParam int size) {
    return userRepository.findAll(PageRequest.of(page, size));
}
"""
    },
    {
        "id": "clean_parameterized_query",
        "label": "clean",
        "diff": """
public List<User> searchUsers(String name) {
    return userRepository.findByNameContaining(name);
}
"""
    },
    {
        "id": "clean_constructor_injection",
        "label": "clean",
        "diff": """
@Service
public class OrderService {
    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public Order getOrder(Long id) {
        return orderRepository.findById(id)
            .orElseThrow(() -> new OrderNotFoundException(id));
    }
}
"""
    },
    {
        "id": "clean_public_transactional",
        "label": "clean",
        "diff": """
@Transactional(rollbackFor = Exception.class)
public void transferFunds(Account from, Account to, double amount) {
    from.debit(amount);
    to.credit(amount);
    accountRepository.save(from);
    accountRepository.save(to);
}
"""
    },
    {
        "id": "clean_secured_endpoint",
        "label": "clean",
        "diff": """
@PreAuthorize("hasRole('ADMIN')")
@DeleteMapping("/users/{id}")
public void deleteUser(@PathVariable Long id) {
    userRepository.deleteById(id);
}
"""
    },
]