# Setting Up Traffic Extension with Model Armor Callout Backend

## Prerequisites

- Docker image for Model Armor Callout backend pushed to a registry.

To create the Docker image, run the following command from the callout Python root directory:
```bash
docker build \
  -f ./extproc/example/Dockerfile \
  -t model-armour-callout-python \
  --build-arg copy_path=extproc/example/model_armor/ \
  --build-arg run_module=service_callout_example .
```
For more information, refer to the Service Extensions documentation.

## Setup Guide
1. Configure VPC for Load Balancer and Backend VMs. Follow the Google Cloud [guide](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#configure-a-network) to set up your VPC.

```bash
# Example commands (adjust as needed)
gcloud compute networks create my-network --subnet-mode=custom
gcloud compute networks subnets create my-subnet \
    --network=my-network --range=10.0.0.0/24 --region=us-central1
```

2. Set up Firewall Rules
Configure firewall rules for backends (Google Cloud [documentation](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#configure_firewall_rules)).
```bash
# Example firewall rule
gcloud compute firewall-rules create allow-health-check \
    --network=my-network \
    --action=allow \
    --direction=ingress \
    --source-ranges=130.211.0.0/22,35.191.0.0/16 \
    --target-tags=allow-health-check \
    --rules=tcp:80
```

3. Reserve IP Address for Load Balancer (Optional)
If needed, reserve an internal IP address following these [instructions](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#reserve-ip).
```bash
gcloud compute addresses create my-ilb-ip \
    --region=us-central1 \
    --subnet=my-subnet
```

4. Create LLM Backend
Set up a managed instance group for your LLM backend. Refer to the Google Cloud [guide](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#create-instance-group-backend) for details.

```bash
# Example commands for creating an instance template and managed instance group
gcloud compute instance-templates create llm-template \
    --machine-type=n1-standard-2 \
    --image-family=debian-10 \
    --image-project=debian-cloud \
    --tags=allow-health-check

gcloud compute instance-groups managed create llm-mig \
    --template=llm-template \
    --size=2 \
    --zone=us-central1-a
```

5. Configure Load Balancer
Create a load balancer to distribute traffic to your LLM backend. You can set up different URL maps for multiple backends if required. Follow the load balancer configuration [guide](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#lb-config) for more information.

```bash
# Example commands for setting up a load balancer
gcloud compute health-checks create http llm-health-check --port 80

gcloud compute backend-services create llm-backend-service \
    --load-balancing-scheme=internal \
    --protocol=http \
    --health-checks=llm-health-check \
    --region=us-central1

gcloud compute backend-services add-backend llm-backend-service \
    --instance-group=llm-mig \
    --instance-group-zone=us-central1-a \
    --region=us-central1

gcloud compute url-maps create llm-url-map \
    --default-service llm-backend-service \
    --region=us-central1

gcloud compute target-http-proxies create llm-proxy \
    --url-map=llm-url-map \
    --region=us-central1

gcloud compute forwarding-rules create llm-forwarding-rule \
    --load-balancing-scheme=internal \
    --network=my-network \
    --subnet=my-subnet \
    --address=my-ilb-ip \
    --ports=80 \
    --target-http-proxy=llm-proxy \
    --target-http-proxy-region=us-central1 \
    --region=us-central1
```

6. Set Up Client Instance
Create a client instance that can interact with the load-balanced LLM backend. Refer to the testing VM setup [guide](https://cloud.google.com/load-balancing/docs/l7-internal/setting-up-l7-internal#test_client).
```bash
gcloud compute instances create test-vm \
    --zone=us-central1-a \
    --subnet=my-subnet \
    --no-address
```

## Configuring Callout Backend for Service Extension

1. Create Callout Server Instance
Set up an instance for the Model Armor callout server. Follow the Google Cloud [guide](https://cloud.google.com/service-extensions/docs/configure-callout-backend-service#configure-extension-service) to create the instance, instance group, and backend service.

**Note:** When creating the callout instance, ensure that the appropriate Cloud API score is enabled for the Model Armor service in the "Security and Access" settings.

2. Configure Traffic Extension
Create a traffic extension for the Model Armor callout backend service using the Google Cloud [documentation](https://cloud.google.com/service-extensions/docs/configure-traffic-extensions#configure_a_traffic_extension_by_using_a_callout).

