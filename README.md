# Target-eye: Dynamic Target Discovery for Prometheus


<details>
	<summary>Target Discovery in Prometheus</summary>

## Overview

With Prometheus' [pull-based model](https://prometheus.io/blog/2016/07/23/pull-does-not-scale-or-does-it/) for collecting metrics, adding new targets, i.e., a 2-tuple of hostname and port where metrics are exposed over HTTP(s), in a basic setup requires manually modifying the config file and reloading Prometheus.  This sort of manual intervention is operationally painful and does not scale or work at all in a distributed system where nodes are ephemeral.  

To address these issues, Prometheus provides a number of [dynamic target discovery mechanisms](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config).  Several of them are built-in to Prometheus, but when the built-in mechanisms do not fit a particular deployment there is also the option of customizing target discovery using [file-based service discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#file_sd_config).

File-based discovery entails writing file(s) of YAML or JSON into a directory that the Prometheus server will watch for changes.  Each YAML or JSON file contains a list of dictionaries describing targets for Prometheus to scrape.  This is what Target-eye provides for FlightAware Prometheus servers. 

</details>

<details>
	<summary>Target-eye Features</summary>


## High Level Overview

Target-eye uses file-based target discovery by managing a directory of JSON files that Prometheus watches for changes and imports targets from.

This means that Target-eye needs to share a directory with the Prometheus server that it's providing target discovery for. 

In addition, the Prometheus server's config needs to contain a [`file_sd_config`](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#file_sd_config) section in its `scrape_configs` pointing at Target-eye's directory of `*.json` files.

When running, Target-eye provides a REST API that can be used by developers to get their applications scraped by Prometheus.  

The REST API makes it possible to use `curl` 1-liners to:

- Add a new target or list of targets (hostname / IP and port) for Prometheus to scrape
- Delete a previously added target or label
- Update a currently registered target 

</details>

<details>
	<summary>Technology Stack</summary>

## Python

Target-eye is written with Python 3.8.3 using the [Quart](https://pgjones.gitlab.io/quart/) web framework (the async version of [Flask](https://flask.palletsprojects.com/en/1.1.x/)).

Its unit tests are written using [`pytest`](https://docs.pytest.org/en/stable/) and [`hypothesis`](https://hypothesis.readthedocs.io/en/latest/).

### Web Stack

It uses [hypercorn](https://github.com/pgjones/hypercorn) as its web-server, which is recommended for production and has excellent TLS support.
</details>

<details>
    <summary>Running Target-eye</summary>

## Docker

Docker is the expected way of running Target-eye.

Before using Docker for Target-eye, copy `.env-sample` to `.env` and modify the variables as appropriate.  

At a minimum set the `FILE_SD_DIR_HOST` variable, which is the directory where Target-eye will write JSON files and Prometheus will inspect for new targets.

To pull down the latest image use the `docker-pull` make target after setting the `IMAGE_TAG` environment variable to `latest`.

Run the pulled image using the `docker-run` make target. 

```bash
make docker-pull-fa
make docker-run
```

### Volumes

Target-eye's container creates the following bind mounts:

- `"${FILE_SD_DIR_HOST}:${FILE_SD_DIRECTORY}"`: From environment variables defined in `.env`, a folder on the host that's shared with Prometheus is mapped into the container
- `/usr/local/flightaware/etc/ssl -> /fa_etc/ssl`: `fa_etc`'s TLS certs and keys are mapped into `/fa_etc/ssl` in the container.  This makes it possible to listen over HTTPS.

## Command-line

From this directory, with the proper Python version and packages installed and environment variables set, the simplest invocation is:

```bash
python -m fa_target_eye 
```

### Configuration 

#### Environment Variables

The recommended way of configuring Target-eye is through environment variables.

For configuring the web-server, any of the supported [config variables found here](https://github.com/pgjones/hypercorn/blob/241d97861875049e0d3a59fb0e01a49bd018cfd8/src/hypercorn/config.py#L40-L82) can be provided as environment variables.

When providing a config variable as an environment variable, make its name uppercase.

For Target-eye itself, provide the `FILE_SD_DIR_HOST` environment variable, which contains the directory path on the host where Target-eye will write and read JSON files containing Prometheus targets.

#### Config Files

**NOTE:** This section is only relevant for development work. 

Configuration can also be provided with Python [INI-style config files](https://docs.python.org/3/library/configparser.html).  

Config files for Target-eye have two sections:

- A `hypercorn` section with [arguments supported by hypercorn](https://pgjones.gitlab.io/hypercorn/tutorials/usage.html) 
- A `target-eye` section for application specific config values

##### `hypercorn` section

Allowed `hypercorn` config values are [found here](https://github.com/pgjones/hypercorn/blob/241d97861875049e0d3a59fb0e01a49bd018cfd8/src/hypercorn/config.py#L40-L82).

##### `target-eye` section

Supported Target-eye config values are:

- `file_sd_directory`: path to the directory of `.json` files managed by Target-eye and read by Prometheus (**required**)
                       can also be provided in the FILE_SD_DIRECTORY environment variable
                       the value in the environment variable overrides the config file if both are provided

</details>


<details>
	<summary>REST API</summary>

## Single URL For all Requests

HTTP requests to Target-eye all use a single URL structure:

```
/<application>/<environment>
```

`<application>` represents the name of the application / service exposing metrics

`<environment>`, which is something like `prod-hou`, `prod-dal`, `staging-hou`, `dev-dal`, contains the environment of the application.

## Targets and Labels

Targets and labels (the only two pieces of information that can be provided as data in REST API requests) are included in the request body either as JSON, YAML or HTTP form-encoding.

### Default Labels

For a given application and environment, all metrics scraped from its targets will include at least two labels:

- `job`: will be set by default to the value of `<application>` but can be overridden in requests
- `env`: will be set by default to the value of `<environment>` but can be overridden in requests

Although `job` and `env` can be overriden, they cannot be removed.

Additional labels can be included in requests.  If so, these labels will be included with all metrics scraped from the targets for a given application and environment.

Since `<application>` and `<environment>` end up being used as label values, they need to adhere to the [Prometheus data model](https://prometheus.io/docs/concepts/data_model/).

### JSON Data Format

To send data in JSON, set the `Content-Type` header to `application/json`.

When provided as JSON, the expected format is a single object:

```
  {
    "targets": [ "<host>", ... ],
    "labels": {
      "<labelname>": "<labelvalue>", ...
    }
  }
```

The `targets` key contains a list of hosts, which can be a hostname, domain name or IPv4 address follwed by an optional port number.  If no port is specified it defaults to `80`.

For example, some valid targets include:

- `localhost:1234`
- `localhost`
- `ackme.dal:12345`
- `dartr.hou.flightaware.com:151234`
- `10.3.3.1:15000,10.3.3.2:15000`


The `labels` key contains an object mapping strings to strings.  Label names and values must adhere to the [Prometheus data model](https://prometheus.io/docs/concepts/data_model/).

### YAML Data Format

To send data in YAML, set the `Content-Type` header to any of the following:

- text/vnd.yaml
- text/yaml
- text/x-yaml
- application/vnd.yaml
- application/x-yaml
- application/yaml

The format of the included YAML should match the structure of the JSON format detailed above:

```
targets:
  - <host1>
  - <host2>

labels:
  label_name1: label_value1
  label_name2: label_value2
```

### Form Encoded

When provided as form encoded data, the list of targets is expected in the `targets` key.

The list is provided as a comma-separated string of host values conforming to the format specified in the section above.

Aside from the `targets` key and its content, any other key-value pairs provided are treated as labels.

## Response Data Format

Target-eye always responds back with JSON.

A 200 status code indicates success; 400 indicates failure.

In the case of failure a JSON object will be returned with a `message` key containing a description of the processing error.

## Supported methods

### GET

`GET` allows seeing what targets and labels are defined for a given application and environment.

```bash
# View the targets defined for the development Houston instance of some service instrumented with Prometheus
curl target-eye.server/service_name/dev-hou
```

If any targets have been defined for the requested application and environment, they are returned [in the format specified by Prometheus for file-based service discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#file_sd_config).  Otherwise an empty list is returned.

### PUT

`PUT` allows replacing the targets and/or labels for a given application and environment.  

It can also be used for specifying the targets and labels for a given application and environment for the first time.


```bash
##
##
## Form Encoded
##
##
# no labels are provided
curl -X PUT -d "targets=hostname1:15000,hostname2:15000" target-eye.server/service_name/dev-hou

# include labels 
curl -X PUT -d "targets=hostname1:15000,hostname2:15000" -d "label1=value1" -d "label2=value2" target-eye.server/service_name/dev-hou

##
##
## JSON
##
##
curl -X PUT -H "Content-Type: application/json" -d '{"targets": ["hostname1:15000","hostname2:15000"]}' target-eye.server/service_name/dev-hou

# If the JSON contents are in a file targets.json
curl -X PUT -H "Content-Type: application/json" -d @targets.json target-eye.server/service_name/dev-hou

##
##
## YAML
##
##

# If the YAML for the targets is contained in a file targets.yml with contents:
#
#  targets:
#    - hostname1:15000
#    - hostname2:15000
#
#  labels:
#    key1: value1
#    key2: value2
curl -X PUT -H "Content-Type: text/yaml" --data-binary @targets.yml target-eye.server/service_name/dev-hou
```

#### PUT Errors

`PUT` requests will only fail if the data included isn't properly formatted.

### POST

`POST` allows for adding to the list of targets for an application and environment, replacing the values of existing labels and adding new labels.  

Like with `PUT`, `POST` can also be used for specifying the targets and labels for given application and environment for the first time.

`POST` cannot be used to replace a current target for an application and environment with a new value.

```bash
##
##
## Form Encoded
##
##
curl -X POST -d "targets=hostname1:15000" target-eye.server/service_name/dev-hou

curl -X POST -d "targets=hostname2:15000" target-eye.server/service_name/dev-hou

##
##
## JSON
##
##
curl -X POST -H "Content-Type: application/json" -d '{"targets": ["hostname1:15000","hostname2:15000"]}' target-eye.server/service_name/dev-hou

##
##
## YAML
##
##

# If the YAML for the targets is contained in a file targets.yml
curl -X PUT -H "Content-Type: text/yaml" --data-binary @targets.yml target-eye.server/service_name/dev-hou
```

#### POST Errors

It is an error to send a POST request with targets if any of the targets already exist.

It is an error to send a POST request with labels if none of the label values in the request change the current values.

### DELETE

`DELETE` requests allow for getting rid of all the targets and labels for an application and environment.

A `DELETE` request without any body data will delete everything for the application and environment in the URL.

`DELETE` requests also allows for selectively getting rid of some of the targets and labels specified for an application and environment.  

A `DELETE` with targets in the request body will delete all of the targets specified.

A `DELETE` with labels in the request body will delete all of the labels specified as long as the values match the values currently defined for the application and environment.

```bash
##
##
## Form Encoded
##
##

# Delete everything for service_name/dev-hou
curl -X DELETE target-eye.server/service_name/dev-hou

# Delete one of the targets
curl -X DELETE -d "targets=hostname2:15000" target-eye.server/service_name/dev-hou

##
##
## JSON
##
##

# Delete one of the targets
curl -X DELETE -H "Content-Type: application/json" -d '{"targets": ["hostname1:15000"]}' target-eye.server/service_name/dev-hou

# Delete one of the targets and one of the labels
curl -X DELETE -H "Content-Type: application/json" -d '{"targets": ["hostname1:15000"],"labels": {"key1":"value1"}}' target-eye.server/service_name/dev-hou

##
##
## YAML
##
##

# If the YAML specifying some of the targets to delete is in a file targets.yml:
#
# targets:
#   - hostname1:15000
#
# labels:
#   key1: value1
curl -X DELETE -H "Content-Type: text/yaml" --data-binary @targets.yml target-eye.server/service_name/dev-hou
```

#### DELETE Errors

It is an error to try to delete all of the targets for an application and environment without also deleting all of the labels.

It is an error to provide an empty targets list.

It is an error to provide a target that is not currently defined for the application and environment.

It is an error to provide an empty object for the labels key in a JSON request.

It is an error to provide a label name or value that is not currently defined for the application and environment.

</details>
