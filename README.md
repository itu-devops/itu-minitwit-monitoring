This is the basic _ITU_MiniTwit_ application (Python 3 and SQLite) with added support for monitoring with Prometheus and Grafana as a Dashboard.

Compared to the application in the master branch, this on monitors frequencies of each function call with a separate counter with the name `minitwit_`+ name of the respective function.

The application is Dockerized. To build the application and a client which simulates users clicking around the front page you have to:

  * Build the application:
```bash
$ docker build -f docker/minitwit/Dockerfile -t <youruser>/webserver .
```

  * Build the test client:
```bash
$ docker build -f docker/minitwit_client/Dockerfile -t <youruser>/minitwitclient .
```


  * Start the application:
```bash
$ docker-compose up
```



Alternatively, you can build and run the application in one step:

```bash
$ docker-compose up --build
```




<!--
docker build -f docker/minitwit/Dockerfile -t helgecph/minitwitserver .
docker build -f docker/minitwit_client/Dockerfile -t helgecph/minitwitclient .

docker run --rm -p 5000:5000 helgecph/minitwitserver:latest

-->



To stop the application again run:

```bash
$ docker-compose down -v
```




After starting the entire application, you can reach:

  * _ITU-MiniTwit_ at http://localhost:5000
  * _ITU-MiniTwit_ metrics for this node at http://localhost:5000/metrics
  * The Prometheus web-client at http://localhost:9090
  * Grafana at http://localhost:3000 (default login and password: `admin`)



------

This `minitwit.py` application was adapted to be monitored with Prometheus with the help of [this](https://blog.codeship.com/monitoring-your-synchronous-python-web-applications-using-prometheus/) blog post.
