
docker build -f docker/minitwit/Dockerfile -t youruser/webserver .
docker build -f docker/minitwit/Dockerfile -t helgecph/minitwitserver .


docker build -f docker/minitwit_client/Dockerfile -t helgecph/minitwitclient .


docker-compose up

docker-compose down -v


docker run --rm -p 5000:5000 helgecph/minitwitserver:latest



https://blog.codeship.com/monitoring-your-synchronous-python-web-applications-using-prometheus/