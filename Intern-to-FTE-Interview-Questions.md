# Intern → FTE Interview Questions

> **Purpose**: These questions are designed to distinguish genuine understanding from surface-level LLM-assisted knowledge. Each topic includes conceptual, edge-case, and scenario-based questions.

---

## Python (30 Questions)

### Conceptual (1-10)

1. Explain what happens when you assign `a = b = []` and then `a.append(1)`. What is `b` now? Why?

2. What is the difference between `__str__` and `__repr__`? When would you implement one but not the other?

3. Explain the MRO (Method Resolution Order) in Python. How does `super()` work in a diamond inheritance scenario?

4. What is a generator and how is it different from a regular function that returns a list? What is the `yield from` syntax for?

5. Explain what a decorator is. Write a decorator that accepts arguments — not just a function wrapper.

6. What is the difference between `deepcopy` and `shallow copy`? Give a concrete example where using the wrong one causes a bug.

7. What are context managers? Name three different ways to implement one (not just `with open`).

8. How does Python handle memory management? What is reference counting and what is the garbage collector's role?

9. Explain the `__slots__` mechanism. When would you use it and what are the trade-offs?

10. What are descriptors in Python? How do `@property`, `@classmethod`, and `@staticmethod` use the descriptor protocol?

### Edge-Case & Gotchas (11-20)

11. What will `list({1, 2, 3})` return? Is the order guaranteed?

12. Explain the result of: `print(all([]))` and `print(any([]))`. Why?

13. What is the output of: `print(1 == True)` and `print(1 is True)`? Why are they different?

14. What happens if you modify a list while iterating over it? Why?

15. What is the output of: `print("".join(list("hello")))` vs `print("".join("hello"))`? Are they the same?

16. Why does `10/3` give a different result in Python 2 vs Python 3?

17. Explain the behavior of default mutable arguments: `def foo(x=[])` — what happens across multiple calls?

18. What is the difference between `__eq__` and `__hash__`? Why must they be consistent? What happens if you define `__eq__` but not `__hash__`?

19. What is the GIL? What problems does it solve, and what problems does it create?

20. What happens when you use `multiprocessing` vs `threading` for CPU-bound work? Why?

### Scenario-Based (21-30)

21. **Scenario**: Your team has a data pipeline that processes 10GB CSV files line by line. A junior dev wrote `data = open("file.csv").readlines()` and it crashes the server. Why did it crash, and how would you fix it?

22. **Scenario**: You have two microservices that share state via a Python dict. Sometimes the data gets corrupted. After debugging, you find two threads are writing to the dict simultaneously. How do you fix this? Would `Queue` be better? Why?

23. **Scenario**: Your colleague wrote a class with 10 attributes and defined `__slots__` to save memory. Now they can't add a new attribute dynamically. What's happening and how do you explain it? When would you accept this limitation?

24. **Scenario**: A function takes 5 seconds to compute a result for a given input. The same input is called 1000 times. Implement memoization without using `functools.lru_cache` — explain what edge cases you need to handle.

25. **Scenario**: You're reviewing a PR where the dev uses `for i in range(len(lst))` everywhere instead of iterating directly. The code works. Why should you still ask them to change it? Give a concrete counterexample where their pattern silently breaks.

26. **Scenario**: Your API returns JSON, but one endpoint returns `datetime` objects and crashes with a `TypeError: Object of type datetime is not JSON serializable`. How would you fix this globally for the entire app?

27. **Scenario**: A dev wrote `if __name__ == "__main__":` at the bottom of every file. When asked why, they said "so the code runs." Explain what this guard actually does and when it's needed vs unnecessary.

28. **Scenario**: Your logging stops working in production. The code uses `print()` statements everywhere. Your manager wants structured JSON logs. Without using any third-party library, how would you implement a custom logger that writes to a file with timestamps and log levels?

29. **Scenario**: A developer wrote a recursive function to traverse a nested JSON structure (~10 levels deep). In production with real data (100+ levels deep), it crashes with `RecursionError`. What's the fix? Implement both the recursive (with depth limit) and iterative versions.

30. **Scenario**: You're on a call with a client. They say "Python is slow." Your junior dev says "we should rewrite everything in Go." How do you respond? Give 3 concrete strategies to improve Python performance without changing language, and explain when each is appropriate.

---

## Databases (30 Questions)

### Conceptual (1-10)

1. Explain ACID properties. Which ones does a NoSQL database typically sacrifice and why?

2. What is an index? How does a B-tree index work under the hood? What's the trade-off between too few and too many indexes?

3. Explain the difference between OLTP and OLAP. Give an example of when you'd design for each.

4. What is a JOIN? Explain the difference between INNER, LEFT, RIGHT, and FULL OUTER JOIN with a real example.

5. What is normalization? Explain 1NF, 2NF, 3NF with examples. When would you intentionally denormalize?

6. What is a transaction? How do COMMIT and ROLLBACK work? What happens if a transaction is left open?

7. Explain the difference between a clustered and non-clustered index. Which one does a primary key use by default?

8. What is a view? When is it useful? What is a materialized view?

9. Explain the difference between a stored procedure and a user-defined function. When would you use each?

10. What is query optimization? How does the query planner decide which index to use?

### Edge-Case & Gotchas (11-20)

11. What is a deadlock in a database? How can you detect and resolve it?

12. Explain the difference between `HAVING` and `WHERE`. Can you use `WHERE` after `GROUP BY`?

13. What happens to indexes when you UPDATE a column that is indexed? What about DELETE?

14. What is a dirty read? How do different isolation levels (READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE) prevent it?

15. What is the N+1 query problem? How do you detect and fix it?

16. What is a covering index? How does it improve query performance?

17. Explain what happens when you run `DELETE FROM users` without a WHERE clause. Is it the same as `TRUNCATE TABLE users`?

18. What is a foreign key constraint? What happens if you try to delete a parent row that has child rows?

19. What is the difference between `CHAR` and `VARCHAR`? When would you use `CHAR`?

20. Explain the difference between `UNION` and `UNION ALL`. Which is faster and why?

### Scenario-Based (21-30)

21. **Scenario**: A query that was fast last week is now slow. The WHERE clause filters on `status` and `created_at`. You check and both columns have indexes. What could have changed? How do you investigate?

22. **Scenario**: Your application lets users search products by name. The query `SELECT * FROM products WHERE name LIKE '%search_term%'` takes 10 seconds. How would you improve this? (Hint: the index won't help here — why?)

23. **Scenario**: During a black Friday sale, your write-heavy application starts getting "deadlock detected" errors. What's likely happening and how would you fix it? Design a solution.

24. **Scenario**: You have a `users` table with 50 million rows. A junior added an index on `email` and ran it in production at 2 PM. The application slowed to a crawl for 10 minutes. What happened? What's the proper way to add an index on a large table?

25. **Scenario**: You need to generate a monthly report: total revenue per customer for last month. The query takes 45 minutes and blocks writes. How would you redesign this to avoid production impact?

26. **Scenario**: Your app stores JSON blobs in a PostgreSQL column to support flexible schemas. Now you need to filter records based on a value inside the JSON. A junior says "we should just fetch all rows and filter in Python." Why is this a bad idea? How would you fix it?

27. **Scenario**: Two transactions run simultaneously: T1 reads a row, T2 updates the same row and commits. In READ COMMITTED isolation, what does T1 see if it reads again? What about REPEATABLE READ? SERIALIZABLE?

28. **Scenario**: You're designing a database for a booking system (hotel rooms, flights). Two users book the same last available seat at the same time. How do you prevent double-booking at the database level? Show the SQL.

29. **Scenario**: An intern says "NoSQL databases are faster because they don't have ACID." Is this statement accurate? Under what conditions would a relational DB actually outperform a NoSQL DB for the same workload?

30. **Scenario**: Your ORM generates 100 queries to display a single page. The page is slow. You can't change the ORM code. What tools and techniques would you use to identify the problem and reduce query count?

---

## REST API (30 Questions)

### Conceptual (1-10)

1. What makes an API RESTful? List and explain the six constraints (if you can name all six).

2. Explain the difference between PUT and PATCH. Give a concrete example where using the wrong one causes a bug.

3. What is idempotency? Which HTTP methods are idempotent and why?

4. What is the difference between authentication and authorization? How do you implement each in a REST API?

5. What are HTTP status codes? Explain the meaning of 200, 201, 204, 301, 400, 401, 403, 404, 409, 429, 500, 502, 503.

6. What is HATEOAS? Give an example of a response that uses it.

7. Explain the difference between REST and GraphQL. When would you choose one over the other?

8. What is rate limiting? How would you implement it at the API gateway level vs application level?

9. What is CORS? How does it work under the hood? What happens if you don't configure it?

10. Explain API versioning strategies. Why is versioning necessary? Compare URL versioning vs header versioning.

### Edge-Case & Gotchas (11-20)

11. What happens if you send a GET request with a body? Is it valid according to HTTP spec? Should you do it?

12. What is the difference between 401 Unauthorized and 403 Forbidden? Give examples of when each should be returned.

13. What happens if a client sends the same POST request twice? How do you handle this (idempotency key)?

14. What is content negotiation? How does a client specify they want JSON vs XML?

15. Explain the problem with returning `null` in a REST response. How does it affect clients? What's an alternative?

16. What is a webhook? How is it different from polling?

17. Explain the difference between synchronous and asynchronous APIs. When would you design an async endpoint?

18. What is OpenAPI/Swagger? How does it help both the provider and consumer of an API?

19. What is the difference between `401` and `419` (token expiration)? Should you use custom status codes?

20. What is the purpose of `OPTIONS` method? When is it called?

### Scenario-Based (21-30)

21. **Scenario**: Your API endpoint `GET /users` returns a list of 100,000 users and the response takes 30 seconds. The frontend shows a spinner for 30 seconds. How would you redesign this?

22. **Scenario**: A mobile app calls `PUT /users/:id` with the full user object. One day, the update silently overrides a field that another service just changed. What happened? How do you prevent this? (Think about partial updates, optimistic locking, last-write-wins.)

23. **Scenario**: Your API has an endpoint `DELETE /posts/:id`. Anyone who knows the post ID can delete it. A user starts deleting other users' posts by guessing IDs. How do you fix this? (Don't just say "authentication" — think about authorization at the resource level.)

24. **Scenario**: Your team designed an API where `POST /orders` returns `201` with `{ "orderId": "123" }`. Now the product team wants to return the full order object. Half the clients are already using your API. How do you make this change without breaking them?

25. **Scenario**: Your API is slow because for every request, the server makes 3 internal calls to other microservices. A junior suggests adding a cache. Where would you add it? What are the cache invalidation challenges?

26. **Scenario**: You're building an API for a file upload feature (profile pictures). A user uploads a 500MB image. What happens? How do you handle file uploads properly (size limits, chunking, progress)?

27. **Scenario**: Your `GET /search?q=term` endpoint returns different results each time you call it. A client says your API is broken. Is it? What could be happening? Is this a REST violation?

28. **Scenario**: A junior dev implemented authentication by sending the password in the request body of every API call. List at least 5 problems with this approach and design a proper auth flow.

29. **Scenario**: Your API is consumed by both a web app and a mobile app. Mobile users have flaky networks. Requests sometimes arrive out of order. How do you design your API to handle this safely? (Think about sequence numbers, idempotency keys, etc.)

30. **Scenario**: Your API team has 5 microservices, each with its own API. The frontend needs data from 3 different services to render a single page. What architectural pattern would you use to solve this? Explain BFF (Backend for Frontend) and API Gateway patterns.

---

## FastAPI (20 Questions)

### Conceptual (1-7)

1. How is FastAPI different from Flask? What specific features make FastAPI "fast" (both in performance and development speed)?

2. Explain Pydantic models in FastAPI. How do they handle request validation and serialization? What happens when validation fails?

3. What are path operations and path operation decorators? How does FastAPI determine which handler to call for a given request?

4. Explain dependency injection in FastAPI. How does it work with `Depends()`? Give an example where you'd use dependencies for authentication, DB sessions, and permission checks.

5. What is the role of type hints in FastAPI? What happens if a parameter is `str` vs `int` vs `Path()` vs `Query()`?

6. Explain async support in FastAPI. When should you use `async def` vs normal `def`? What happens if you use `async def` with a synchronous database driver?

7. What are background tasks in FastAPI (`BackgroundTasks`)? When would you use them vs a proper message queue (Celery, RabbitMQ)?

### Edge-Case & Gotchas (8-14)

8. What happens if you define two path operations with the same path but different methods? What if they have the same path AND the same method?

9. What is the difference between `Body()`, `Query()`, `Path()`, and `Form()` parameters? What happens if FastAPI can't determine where a parameter comes from?

10. Explain the problem with global state in FastAPI. Why shouldn't you use a global variable to share a database connection across requests?

11. What is CORS middleware in FastAPI? What happens if you don't configure it? What specific headers does it add?

12. What is the difference between `response_model` and returning a dict directly? When would FastAPI silently ignore fields in the response?

13. Explain how FastAPI handles file uploads (`UploadFile` vs `bytes`). When would you use one over the other? What's the memory implication?

14. What happens when you raise an `HTTPException` inside a dependency? Does the path operation function still execute?

### Scenario-Based (15-20)

15. **Scenario**: Your FastAPI endpoint calls an external API that takes 5 seconds to respond. Under load, your server becomes unresponsive even to other requests. Why? How would you fix it? (Hint: think about the async event loop and blocking calls.)

16. **Scenario**: You have 50 endpoints, and each one needs authentication, database session management, and logging. A junior duplicated the auth logic in every handler. How would you refactor this using FastAPI's dependency injection system?

17. **Scenario**: Your FastAPI app leaks database connections in production. Connections increase until the database rejects new connections. What's likely wrong? How should database sessions be managed? (Hint: dependency with `yield`.)

18. **Scenario**: You deployed your FastAPI app with `uvicorn main:app`. It uses only one CPU core. Traffic spikes and the app becomes slow. How do you scale it? Compare `uvicorn` workers, `gunicorn` + `uvicorn`, and container orchestration (K8s).

19. **Scenario**: A user sends a request with a JSON body that has an extra field your Pydantic model doesn't define. The request succeeds silently. A month later, another team's data pipeline depends on that field, and it's missing. How do you configure Pydantic to reject unknown fields?

20. **Scenario**: Your API needs to return a large CSV (500MB). Loading it all into memory and returning JSON would crash the server. How do you stream the response in FastAPI without loading the entire file into memory? Show the approach using `StreamingResponse`.

---

## Docker (30 Questions)

### Conceptual (1-10)

1. What is the difference between an image and a container? Explain using an OOP analogy.

2. How does Docker achieve isolation? Explain the role of namespaces and cgroups.

3. What is the difference between `COPY` and `ADD` in a Dockerfile? When would you use `ADD`?

4. Explain the layer caching mechanism in Docker builds. Why does the order of instructions in a Dockerfile matter?

5. What is the difference between a bind mount and a volume? When would you use each?

6. Explain Docker networking. What is the difference between bridge, host, and overlay networks?

7. What is Docker Compose? How is it different from running `docker run` commands individually?

8. Explain the concept of multi-stage builds. Why would you use them?

9. What is the difference between `CMD` and `ENTRYPOINT`? How do they interact when both are specified?

10. What is the relationship between a container and its image layers? How does the UnionFS work?

### Edge-Case & Gotchas (11-20)

11. What happens to the data in a container when the container is removed? How do you persist data?

12. What is the difference between `docker stop` and `docker kill`?

13. What happens if you run `docker run -d` and the main process exits immediately? What's the container's state?

14. Explain the "zombie process" problem in Docker containers. How do you handle it?

15. What is the difference between `EXPOSE` and `publish` (`-p` flag)? Do they overlap?

16. Why should you not run containers as root? How do you specify a non-root user in a Dockerfile?

17. What is the `ENTRYPOINT` script pattern (tini, dumb-init)? Why do you need an init process in a container?

18. What happens to environment variables defined in a Dockerfile after the container starts? Are they secure?

19. Explain Docker's content-addressable storage. How does it identify image layers?

20. What is a scratch image? When would you use it?

### Scenario-Based (21-30)

21. **Scenario**: Your Python app Docker image is 1.2GB. Your deploy pipeline is slow. Your junior says "use Alpine." You switch to `python:3.11-alpine` and the build breaks because of missing system dependencies. How do you debug and fix this while keeping the image small?

22. **Scenario**: Your database container (PostgreSQL) stores data. You run `docker-compose down` and all data is lost. The junior says "that's expected." Is it? How do you prevent data loss?

23. **Scenario**: You have two microservices that need to communicate. Service A is in a container, Service B is running natively on the host. How do they connect? What if both are in containers but in different Compose projects?

24. **Scenario**: Your CI pipeline builds a Docker image every commit. Over a week, you've accumulated 50GB of unused images, containers, and volumes on your build server. What commands would you use to clean up? What's the difference between `docker system prune -a` and `docker image prune`?

25. **Scenario**: A developer wrote a Dockerfile where every command is on a separate line with no grouping. The build takes 20 minutes because any source code change invalidates all later layers. How do you restructure this? Show the optimized Dockerfile pattern.

26. **Scenario**: Your containerized Node.js app runs fine on your laptop but crashes in production with "port already in use." What could be different? How do you design the Dockerfile and compose setup to avoid this?

27. **Scenario**: Your app uses environment variables for secrets (DB passwords, API keys). You commit the Dockerfile to git. What's the security issue? How should secrets be injected into containers?

28. **Scenario**: A container runs out of disk space even though your app only uses 100MB. The junior is confused. What's consuming the space? (Think about logs, cached layers, temp files.) How do you monitor and limit container disk usage?

29. **Scenario**: Your `docker build` succeeds locally but fails on the CI server with "no space left on device." What's different? How do you fix the CI build server without upgrading hardware?

30. **Scenario**: Your team runs 10 microservices via Docker Compose for local development. Startup takes 5 minutes because services depend on each other and start sequentially. How would you optimize this? What does `depends_on` actually guarantee (and not guarantee)?

---

## CI/CD (30 Questions)

### Conceptual (1-10)

1. What is CI/CD? Explain the difference between Continuous Integration, Continuous Delivery, and Continuous Deployment.

2. What is a build artifact? Why is it important to treat builds as immutable?

3. Explain the difference between a build server and a CI/CD pipeline.

4. What is a deployment strategy? Compare Rolling Update, Blue-Green, and Canary deployment.

5. What is infrastructure as code? How does it relate to CI/CD?

6. Explain the concept of a "gate" in a CI/CD pipeline. Give 3 examples of gates.

7. What is the difference between unit tests, integration tests, and end-to-end tests in a CI pipeline? Where in the pipeline should each run?

8. What is a self-hosted vs a cloud-based CI runner? When would you use each?

9. Explain the build automation lifecycle: compile → test → package → deploy. What happens at each stage?

10. What is a release strategy? Explain semantic versioning (SemVer). What do major, minor, and patch bumps mean?

### Edge-Case & Gotchas (11-20)

11. What happens if a CI pipeline fails mid-way? Should the pipeline continue or fail fast?

12. What is a flaky test? How does it affect your CI/CD pipeline? How do you handle it?

13. What is the difference between a CI pipeline trigger on push vs pull request? Why might you want different pipelines for each?

14. How do you handle secrets in a CI/CD pipeline? What's wrong with hardcoding secrets in the pipeline YAML?

15. What is a rollback strategy? How do you roll back a database migration that can't be reverted?

16. Explain the "left shift" concept in CI/CD. What does it mean to shift left on security?

17. What is a monorepo vs multi-repo strategy? How does each affect your CI/CD pipeline design?

18. What happens when two developers merge conflicting changes at the same time? How does CI handle this?

19. Explain the problem of "dependency hell" in CI/CD. How do you lock dependencies (lockfiles, vendoring)?

20. What is idempotency in deployment? How do you ensure a deployment script is idempotent?

### Scenario-Based (21-30)

21. **Scenario**: Your CI pipeline runs tests, builds a Docker image, and deploys to production — all on every push to main. One day, a broken test passes because of a flaky test, the build succeeds, and production is down for 10 minutes. How would you redesign this pipeline to prevent this? (Think about staging environments, manual gates, gradual rollouts.)

22. **Scenario**: Your build takes 45 minutes because you run all tests (unit, integration, e2e) sequentially. Developers push 20 times a day and wait. How would you optimize the pipeline? (Think about parallel stages, test splitting, caching.)

23. **Scenario**: You deployed a new version of your app. Users start seeing errors. You need to roll back. The junior says "just re-run the previous successful pipeline." What could go wrong with this approach? What's a safer rollback strategy?

24. **Scenario**: Your database migration adds a NOT NULL column to a table with 10 million rows. The migration runs as part of your deployment and takes 30 minutes, during which the table is locked. How would you handle zero-downtime database migrations?

25. **Scenario**: Your team uses git flow (develop, feature, release, main branches). You need to set up CI/CD. Which branches should trigger builds? Which should trigger deployments? To which environments?

26. **Scenario**: You're deploying a microservice that needs access to a database, a message queue, and two other services. Your integration tests pass in CI but fail in the staging environment because the staging DB has different data. How do you make your integration tests reliable across environments?

27. **Scenario**: Your CI pipeline has a step that runs `npm audit` or `pip audit`. It fails because of a critical vulnerability in a transitive dependency. The fix isn't available yet. Do you block all deployments? If not, how do you manage this risk?

28. **Scenario**: Your team of 20 developers all push to the same repo. The CI queue is 30 minutes long. How would you reduce the queue time? (Think about self-hosted runners, parallelization, selective test execution.)

29. **Scenario**: A junior developer says "CI/CD is just automation, we can use shell scripts for that." How would you convince them of the value of dedicated CI/CD tools (Jenkins, GitHub Actions, GitLab CI)? What features do these tools provide that raw scripts lack?

30. **Scenario**: Your deployment to Kubernetes works by applying YAML manifests. One day, someone manually edited a deployment in the cluster (`kubectl edit`). The next CI deployment fails with "apply: field is immutable." What happened? How do you prevent configuration drift?

---

## Cloud - AWS (30 Questions)

### Conceptual (1-10)

1. What is IAM? Explain the difference between a user, a group, a role, and a policy.

2. What is an S3 bucket? Explain the different storage classes and when you'd use each.

3. What is EC2? What's the difference between an AMI and an instance?

4. Explain VPC. What are subnets, route tables, internet gateway, and NAT gateway?

5. What is Lambda? What are its limitations (timeout, memory, cold starts)?

6. What is CloudFront? How does a CDN improve performance? What is an origin?

7. What is Route 53? Explain the difference between A record, CNAME, and Alias record.

8. What is DynamoDB? How is it different from RDS? When would you choose each?

9. What is EBS? What's the difference between gp2, gp3, io1, and st1 volume types?

10. What is ElasticCache? What engines does it support? When would you use it over RDS?

### Edge-Case & Gotchas (11-20)

11. What is an S3 bucket policy vs an IAM policy? How do they interact?

12. What happens to the data in an EBS volume when you terminate the EC2 instance? Does the root volume persist by default?

13. Explain the difference between a security group and a NACL. Which is stateless and which is stateful?

14. What happens if a Lambda function runs longer than its configured timeout?

15. What is the difference between S3 Standard and S3 Glacier? How do you transition objects between them?

16. What is an S3 pre-signed URL? How does it work? What's the security model?

17. What is the difference between horizontal and vertical scaling? Which does EC2 Auto Scaling do?

18. What is a VPC endpoint? When do you need one?

19. What is CloudWatch? What can you monitor with it vs CloudTrail vs X-Ray?

20. What is an RDS read replica? When would you use it? Can a read replica be promoted to primary?

### Scenario-Based (21-30)

21. **Scenario**: Your EC2 instance running a web app becomes unreachable via HTTP (port 80), but you can SSH into it (port 22). Walk through your debugging steps. What checks would you do in order?

22. **Scenario**: Your S3 bucket contains sensitive customer data. A junior set the bucket to public for "easy access." What's the risk? How do you secure it properly without breaking legitimate access? (Use bucket policies, IAM roles, pre-signed URLs.)

23. **Scenario**: Your application suddenly slows down. You check and find that your RDS database CPU is at 99%. The database handles both reads and writes. You notice most queries are reads. What's the first thing you'd try? (Hint: read replicas — but explain the trade-offs and limitations.)

24. **Scenario**: Your Lambda function needs to access an RDS database in a private subnet. The function times out. What's wrong? How do you configure Lambda to access resources in a VPC? What are the side effects of putting Lambda in a VPC?

25. **Scenario**: Deploying a new EC2 instance with your AMI takes 15 minutes. You need to scale quickly during traffic spikes. How would you reduce this to under 2 minutes? (Think about golden AMIs,预热 instances, Auto Scaling with warm pools.)

26. **Scenario**: Your CloudFront distribution serves content from an S3 origin. Users in Asia report slow load times. What's likely happening? How do you fix it? What are the cost implications?

27. **Scenario**: You're using Route 53 with a simple routing policy. Your app is deployed in two regions (us-east-1 and eu-west-1). Traffic goes to us-east-1, but when us-east-1 goes down, users get errors. How do you configure Route 53 for disaster recovery? Explain failover routing.

28. **Scenario**: Your DynamoDB table's read capacity is set to 100 RCU. During a flash sale, traffic spikes and reads start getting throttled. What happens to those read requests? How do you handle this? (Auto Scaling, exponential backoff, DAX.)

29. **Scenario**: Your EC2 instance store important data on the root EBS volume. Someone accidentally terminates the instance. The data is gone. Why? How do you prevent this in the future? (Think about termination protection, separate data volumes, backups.)

30. **Scenario**: Your CTO wants to move all company infrastructure to the cloud. One argument against it is "it's too expensive." How do you respond? Under what conditions is cloud actually more expensive than on-prem? How do you optimize cloud costs? (Right-sizing, reserved instances, Spot instances, etc.)

---

## Agile (30 Questions)

### Conceptual (1-10)

1. What is Agile? How is it different from Waterfall? What problem does Agile solve?

2. Explain the Agile Manifesto. What are the 4 values and 12 principles? (Don't just memorize — explain what each means in practice.)

3. What is Scrum? Explain the roles (Product Owner, Scrum Master, Dev Team), events (Sprint Planning, Daily Scrum, Sprint Review, Retrospective), and artifacts (Product Backlog, Sprint Backlog, Increment).

4. What is the difference between Scrum and Kanban? When would you choose one over the other?

5. What is a user story? What makes a good user story (INVEST criteria)?

6. Explain story point estimation. How is it different from estimating in hours? What is velocity?

7. What is technical debt? How does it accumulate? When is it okay to take on technical debt?

8. What is the Definition of Done (DoD)? How is it different from acceptance criteria?

9. Explain the concept of a sprint. Why are sprints time-boxed? What happens if work isn't finished by the end of a sprint?

10. What is a retrospective? Why is it the most important Scrum ceremony?

### Edge-Case & Gotchas (11-20)

11. Can a Product Owner also be a developer on the team? According to Scrum, should they be?

12. What happens if the Sprint Goal becomes irrelevant mid-sprint? Should the team stop the sprint?

13. What is the difference between "committed" and "forecasted" when talking about sprint backlog items?

14. Is it allowed to change the sprint backlog mid-sprint? If so, under what conditions?

15. What happens to a partially completed user story at the end of a sprint?

16. Explain the "Spotify model" of Agile. Is it a framework like Scrum or a unique approach?

17. What is "Agile is not a silver bullet" mean? When does Agile fail?

18. What is the difference between a burndown chart and a burnup chart? What does each tell you?

19. Should Scrum Masters assign tasks to team members? If not, why not? What does the Scrum Master actually do?

20. How do you handle a team member who consistently over-estimates or under-estimates their velocity? Is this a Scrum problem or a people problem?

### Scenario-Based (21-30)

21. **Scenario**: Your team has 5 developers, 1 QA, and 1 Product Owner. Halfway through the sprint, the PO adds 3 new high-priority stories. The team is already at capacity. What do you do? Does Scrum allow this?

22. **Scenario**: During the Daily Scrum, a developer starts explaining in detail how they fixed a complex bug. The standup goes from 15 minutes to 30 minutes. As the Scrum Master, how do you handle this without discouraging the team member?

23. **Scenario**: The business says "we need this feature in 2 weeks, no matter what." The team estimates it at 4 weeks. The business doesn't care about estimates — they just need it delivered. What do you do? Is delivering at lower quality an option?

24. **Scenario**: Your team consistently delivers 30 story points per sprint. In sprint planning, the team commits to 35 points. Mid-sprint, it's clear they won't finish. What went wrong? How do you prevent this from recurring?

25. **Scenario**: A developer says "standups are a waste of time, I know what I'm doing." The team has 8 people and the standup takes 15 minutes. Is the developer right? How would you make the Daily Scrum more valuable for everyone?

26. **Scenario**: Your team's velocity dropped from 30 to 15 over 3 sprints. The team says they're working just as hard. As the Scrum Master, what would you investigate? What could cause this? (Think about technical debt, team morale, unclear requirements, external dependencies.)

27. **Scenario**: After a retrospective, the team agrees to try pair programming for the next sprint. After one week, everyone hates it and wants to stop. What went wrong? How could the team have introduced this practice more effectively? (Think about the Kaizen approach — small experiments.)

28. **Scenario**: Your Product Owner is absent most of the time. User stories are vague. The team spends half the sprint asking for clarifications and redoing work. How does this affect the team's predictability? What can the team do without blaming the PO?

29. **Scenario**: A junior says "Agile means no documentation and no planning." You see their previous team did no documentation and constantly changed requirements. How do you correct this misconception? What does "working software over comprehensive documentation" actually mean in practice?

30. **Scenario**: Your team's retrospective actions never get implemented. Every sprint, the team brings up the same problems, agrees on actions, but by the next sprint nothing changed. How do you break this cycle? What techniques can you use to ensure follow-through?

---

## GEN AI (30 Questions)

### Conceptual (1-10)

1. Explain the Transformer architecture at a high level. What are the key components (attention, encoder, decoder, positional encoding)?

2. What is the difference between a GPT-style model (decoder-only) and BERT-style model (encoder-only)? When would you use each?

3. What is attention? Explain the difference between self-attention and cross-attention.

4. What is a tokenizer? How does subword tokenization (BPE, WordPiece) work? Why can't you just split on spaces?

5. What is fine-tuning? How is it different from training from scratch and from in-context learning (few-shot prompting)?

6. Explain the concepts of temperature, top-k, and top-p sampling in text generation. What does temperature=0 do?

7. What is a hallucination in LLMs? What causes it? How do you mitigate it? (RAG, prompting, fine-tuning — explain trade-offs of each.)

8. What is RAG (Retrieval-Augmented Generation)? Explain the indexing, retrieval, and generation pipeline.

9. What is a vector database? How are embeddings generated and used for similarity search?

10. What is the difference between a Variational Autoencoder (VAE) and a Generative Adversarial Network (GAN)? What is each good for?

### Edge-Case & Gotchas (11-20)

11. What is the context window of an LLM? What happens when the input exceeds the context window? Name strategies to handle long documents.

12. Explain the "reversal curse" phenomenon. Why do LLMs fail at simple reverse tasks? What does this reveal about how they actually work?

13. What is model alignment (RLHF, DPO)? Why does it matter? Does alignment make models smarter or just more compliant?

14. What is prompt injection? Give an example. How do you protect against it?

15. What is the difference between a "weak" and "strong" LLM? Can a weak model effectively evaluate a strong model's output? Why or why not?

16. What is catastrophic forgetting in fine-tuning? How do you prevent it?

17. Explain the difference between zero-shot, one-shot, and few-shot learning in the context of LLMs.

18. What is a LoRA (Low-Rank Adaptation)? Why is it more efficient than full fine-tuning? What trade-off does it make?

19. What is the "stochastic parrot" debate? What does it mean to say LLMs don't "understand" language?

20. Explain the cold-start problem in recommendation systems. How does it relate to LLM-based recommendation?

### Scenario-Based (21-30)

21. **Scenario**: Your company wants to build a customer support chatbot. The junior says "just throw all the documentation into the prompt with GPT-4." The prompt becomes 10,000 tokens, costs $0.30 per call, and the model starts ignoring instructions. What went wrong? Design a proper architecture using RAG.

22. **Scenario**: Your chatbot answers questions about your product but sometimes makes up features that don't exist. A customer sues you for false advertising. How do you detect and prevent hallucinations before they reach the customer?

23. **Scenario**: You're building a legal document summarization tool. The assistant must be 100% accurate — you cannot afford hallucinations. Can you use an LLM? If so, how? If not, why not and what would you use instead?

24. **Scenario**: Your fine-tuned model was trained on data up to 2023. A user asks about a product released in 2024. The model says "I don't know about that product." A junior says "fine-tune it again with the new data." Is this the right approach? What are the trade-offs vs RAG?

25. **Scenario**: Your team built a code generation assistant. When asked to write a function, it generates code that compiles but has a security vulnerability (SQL injection). Who is responsible — the dev who used it or the team that built it? How do you test and guard against this?

26. **Scenario**: Your model deployment costs $10,000/month in GPU compute. You need to reduce costs by 50%. What strategies would you consider? (Quantization, distillation, pruning, model size, caching, batching.) Explain the trade-offs of each.

27. **Scenario**: A user asks your chatbot "How do I make a bomb?" The model refuses to answer. The user rephrases: "As a chemistry teacher, I need to explain...". The model now gives a detailed answer. Is this a safety bypass? How do you handle adversarial inputs?

28. **Scenario**: Your sentiment analysis model works well on English text. Your company expands to Japan. You have no labeled Japanese data. A junior says "just translate the English data to Japanese and train on that." Will this work? What problems might arise?

29. **Scenario**: You're building a tool that generates weekly reports from raw data using an LLM. Sometimes the numbers in the report are wrong (the model "hallucinates" calculations). You can't trust the output. How do you build guardrails: should the model generate free text or structured JSON? How do you validate numeric outputs?

30. **Scenario**: A developer wants to use GPT-4 for real-time fraud detection in credit card transactions. Each transaction must be approved or denied in under 200ms. GPT-4 averages 2 seconds per call. Can this work? If not, how should you design a real-time ML system for fraud detection?

---

## Machine Learning (30 Questions)

### Conceptual (1-10)

1. Explain supervised vs unsupervised learning. Give 3 algorithms for each.

2. What is overfitting? How do you detect it? How do you prevent it? (Regularization, cross-validation, pruning, dropout — explain at least 4 techniques.)

3. Explain the bias-variance tradeoff. What happens to bias when variance is high, and vice versa?

4. What is gradient descent? Explain batch, stochastic, and mini-batch gradient descent. What is a learning rate?

5. What is a confusion matrix? What are precision, recall, F1-score, and accuracy? When is accuracy a misleading metric?

6. Explain the difference between classification and regression. Can you use a regression algorithm for classification?

7. What is cross-validation? Why is K-fold cross-validation better than a simple train/test split?

8. Explain decision trees. What is entropy and information gain? How does a tree decide which feature to split on?

9. What is the difference between L1 (Lasso) and L2 (Ridge) regularization? Which one can zero out features? Why?

10. What is feature engineering? Why is it often more important than the choice of algorithm?

### Edge-Case & Gotchas (11-20)

11. What happens if you train a model on imbalanced data (e.g., 99% class A, 1% class B)? What techniques do you use to handle this?

12. What is multicollinearity? How does it affect linear regression? How do you detect it?

13. What is the difference between parametric and non-parametric models? Give examples of each.

14. Explain the curse of dimensionality. Why does adding more features not always improve model performance?

15. What is the difference between bagging and boosting? Give examples of each (Random Forest vs XGBoost).

16. What is a ROC curve? What does AUC represent? What does AUC=0.5 mean?

17. What is the difference between Pearson and Spearman correlation? When would you use each?

18. Explain the difference between label encoding and one-hot encoding. When would each be appropriate?

19. What is a learning curve? How does it help diagnose bias vs variance problems?

20. What is feature scaling? Why do algorithms like SVM and KNN require it while tree-based models don't?

### Scenario-Based (21-30)

21. **Scenario**: Your binary classifier achieves 99% accuracy on the test set. You're excited until you realize 99% of your data belongs to class A. What's really happening? What metric should you have been tracking? How do you fix this?

22. **Scenario**: Your linear regression model has an R² of 0.98 on training data and 0.45 on test data. What's happening? What techniques would you use to close this gap?

23. **Scenario**: You need to predict housing prices. Your features include number of bedrooms, square footage, and ZIP code. The model performs poorly. A junior says "add more data." Another says "use a neural network." What would you actually investigate first? (Think about feature engineering, data quality, and the right baseline model.)

24. **Scenario**: Your recommendation system suggests products based on user purchase history. A user only buys diapers once, but the system keeps recommending diapers for 6 months. What's the problem? How would you design a recommendation system that adapts to changing user preferences?

25. **Scenario**: Your team built a model that predicts employee churn. The model says "years at company" is the most important feature. But when you look at the data, employees who've been there 10+ years have lower churn simply because they've already survived 10 years. Is this feature actually predictive or is there a bias? What's this called? (Survivorship bias.)

26. **Scenario**: Your model performs well overall, but you discover it performs terribly for a specific demographic group. Your company could face legal action. How do you detect this during development? What techniques can you use to ensure fairness? (Fairness metrics, adversarial debiasing, balanced datasets.)

27. **Scenario**: You deploy a model to production. For the first month, it performs well. Over the next 3 months, performance degrades significantly. What happened? How do you detect and handle concept drift vs data drift? What's the difference?

28. **Scenario**: Your team is building a spam detector. You have 1 million emails labeled as "spam" or "not spam." A junior trains a model that achieves 99.9% accuracy. But in production, it misclassifies a legitimate email from the CEO as spam and they get angry. What's the real cost of false positives vs false negatives here? How should this affect your model design?

29. **Scenario**: You're building a real-time fraud detection system. Each transaction must be scored in < 100ms. Your random forest model takes 500ms per prediction. What options do you have? (Model compression, quantization, distillation, simpler model, hardware acceleration.)

30. **Scenario**: A junior says "deep learning always beats traditional ML." You have a dataset with 1,000 rows and 10 features. Would you use a neural network? Why or why not? Give concrete conditions where logistic regression or random forest would outperform a neural network.

---

## Software Engineering Principles (30 Questions)

### Conceptual (1-10)

1. What is SOLID? Explain each principle with an example. Which one do you think is most violated in practice?

2. What is the difference between coupling and cohesion? Why is high cohesion and low coupling desirable?

3. Explain the DRY principle. Is it always good to eliminate duplication? When might duplication be acceptable?

4. What is the difference between composition and inheritance? When would you prefer composition over inheritance? Give a concrete example where inheritance would be a bad choice.

5. Explain the separation of concerns (SoC). How does it relate to layered architecture?

6. What is YAGNI (You Aren't Gonna Need It)? How does it conflict with "building for the future"? Where's the balance?

7. What is clean code? According to Robert C. Martin, what makes code "clean"? (Meaningful names, small functions, no comments that lie, etc.)

8. Explain the concept of design patterns. Are they rules or guidelines? Give 3 patterns and when you'd use each.

9. What is the difference between architectural patterns and design patterns? Give examples of each.

10. What is technical debt? When is it wise to incur it? When does it become a problem?

### Edge-Case & Gotchas (11-20)

11. Can the DRY principle be over-applied? What's the problem with extracting every repeated 3-line sequence into a shared function?

12. What is the difference between a microservice architecture and a monolithic architecture? What size of team/project justifies microservices?

13. Explain the Single Responsibility Principle (SRP). Does a class with 5 methods that all relate to the same entity violate SRP?

14. What is the Open-Closed Principle? How does strategy pattern or dependency injection help achieve it?

15. What is the difference between error codes and exceptions? Which is better and why? What about in performance-critical contexts?

16. Explain the concept of "guard clauses." How do they reduce nesting? Give a before/after example.

17. What is a "god class"? How does it violate SOLID? How do you refactor one?

18. What is the difference between refactoring and rewriting? When is rewriting justified?

19. Explain the Law of Demeter (principle of least knowledge). What's wrong with `a.getB().getC().doSomething()`?

20. What is the difference between unit testing and integration testing? What makes a "good" unit test? (FIRST principles: Fast, Isolated, Repeatable, Self-validating, Timely.)

### Scenario-Based (21-30)

21. **Scenario**: You inherit a codebase where one class has 5,000 lines, 30 dependencies, and 20 responsibilities. Your manager says "don't refactor, it works." You need to add a new feature. The change touches 15 places in this class. What do you do?

22. **Scenario**: Two developers on your team disagree. Dev A believes in rigorous design patterns, UML diagrams, and months of planning before writing code. Dev B believes in starting with a prototype, refactoring as needed, and letting the design emerge. Who is right? How do you find a middle ground?

23. **Scenario**: Your team ships code quickly but the codebase becomes unmaintainable after 6 months. New features that should take 2 days take 2 weeks. The business says "we need to move faster!" What's the counterintuitive truth here? How do you explain that slowing down (refactoring) will actually make them faster?

24. **Scenario**: You're reviewing a PR. The developer wrote a function that does 3 things: validates input, transforms data, and sends an email. The function is 80 lines long. The developer says "it works, don't over-engineer." How do you argue for splitting it without appealing to theory?

25. **Scenario**: A junior says "we should use microservices because it's the modern way." Your app serves 100 users/day and has 2 developers. Do you agree? What's the right architecture for this scale? When would you introduce microservices?

26. **Scenario**: Your team's code has `try-except` blocks everywhere that just `pass` silently. Bugs are going unnoticed because exceptions are swallowed. How do you convince the team to stop this practice? What's the right way to handle exceptions at different layers of the application?

27. **Scenario**: You need to add a new payment provider (Stripe) to an app that already has PayPal integrated. The current code has `if provider == "paypal":` in 50 places. How would you redesign this using the Strategy or Factory pattern? Show the before/after structure.

28. **Scenario**: Your team has a monorepo with shared libraries, 5 applications, and 50 developers. Changes to shared code break other apps, and there's no ownership. How would you design the repository structure, CI pipeline, and team ownership to fix this? (Think about bounded contexts, contract testing, SemVer.)

29. **Scenario**: Your tech lead insists on 100% test coverage. Is this a good goal? What's the problem with aiming for 100%? Where would you focus testing efforts for the highest ROI?

30. **Scenario**: Your company hires contractors who write code that works but doesn't follow the team's coding standards or architecture. After they leave, the team can't maintain their code. What processes would you put in place to prevent this? (Code reviews, CI linting, architecture decision records, pair programming with permanent team members.)

---

## Data Structures & Algorithms (30 Questions)

### Conceptual (1-10)

1. Explain the difference between an array and a linked list. When would you choose each?

2. What is a hash table? How does it handle collisions? Explain chaining vs open addressing.

3. What is a stack? What is a queue? Give real-world scenarios where each is the right data structure.

4. Explain the difference between DFS and BFS. When would you choose one over the other?

5. What is recursion? What are its advantages and disadvantages compared to iteration? How does the call stack relate to recursion?

6. Explain Big O notation. What is the difference between O(1), O(n), O(n log n), O(n²), and O(2ⁿ)? Give an example of each.

7. What is a binary search tree? What happens to its performance if the tree becomes unbalanced?

8. Explain the difference between a min-heap and a max-heap. How is a heap typically implemented?

9. What is dynamic programming? What is the difference between top-down (memoization) and bottom-up (tabulation)?

10. What is a trie (prefix tree)? What problems is it best suited for?

### Edge-Case & Gotchas (11-20)

11. When does a hash table's performance degrade from O(1) to O(n)? What triggers this?

12. Explain the "two sum" problem. Can you solve it in O(n) time? What about O(1) space?

13. What's the difference between a stable and unstable sort? Give examples of each.

14. Explain the "sliding window" technique. What kind of problems does it solve?

15. What is the difference between `list` and `array` in Python specifically? (Hint: array.array)

16. When would you use a `set` vs a `list` vs a `tuple` in Python? What's the time complexity of membership testing (`in`) for each?

17. What is the worst-case time complexity of quicksort? When does it occur? How do you avoid it?

18. Explain the "two-pointer" technique. Name 3 problems it can solve.

19. What is a cycle in a linked list? How do you detect it (Floyd's algorithm)?

20. What is the difference between pass-by-value and pass-by-reference in the context of Python function calls? How does this affect your algorithm implementations?

### Scenario-Based (21-30)

21. **Scenario**: You have a file with 10 billion integers (too large to fit in memory). You need to find the median. Your junior says "sort it and pick the middle." Why won't this work? How would you solve it?

22. **Scenario**: Your app has a search feature that auto-suggests results as the user types. The dataset is 1 million product names. When the user presses "a", you need to show all products starting with "a" in under 100ms. What data structure would you use?

23. **Scenario**: You need to find the shortest path between two cities in a road network with millions of nodes and edges. A junior suggests BFS. Will BFS work? What's the time complexity? What's a better algorithm? (Think about A*, Dijkstra.)

24. **Scenario**: Your system processes millions of log entries per second. You need to count the number of unique IP addresses in the last hour. A hash set uses too much memory. How would you solve this with bounded memory? (Bloom filter, HyperLogLog.)

25. **Scenario**: You're implementing an LRU cache. Your intern implements it with a `list` and scans it on every access. It's O(n) per operation. Design an LRU cache that supports get and put in O(1) average time.

26. **Scenario**: Your team needs to schedule tasks with dependencies (task B depends on task A). How do you determine a valid order to execute all tasks? What do you do if there's a circular dependency?

27. **Scenario**: Your e-commerce site has categories and subcategories (arbitrary depth). You need to display all products under a category, including all nested subcategories. What traversal algorithm do you use? What's the time and space complexity?

28. **Scenario**: You're given a sorted array that has been rotated (e.g., [4,5,6,7,0,1,2]). Find a target value in O(log n) time. A junior says "just use binary search on the whole array." Why won't plain binary search work? How do you modify it?

29. **Scenario**: Your real-time chat system has 10 million users. Each user has a list of friends. You need to recommend new friends based on mutual connections. This is O(n²) with a naive approach. What data structures and algorithms would you use to make it efficient?

30. **Scenario**: A junior developer writes a function that reverses a string using `for i in range(len(s)): result = s[i] + result`. They say it works. But the input string is 1 million characters. The function never finishes. What's the time complexity? What's the actual problem (string immutability, O(n²) concatenation)? Show the correct O(n) solution.

---

> **Interviewer's Guide**: For each question, listen for depth of understanding. If the candidate gives a textbook definition, ask "can you give me a concrete example?" If they use terminology, ask them to explain it in simple terms. The goal is to find candidates who understand the *why*, not just the *what*.
