# tf2sam
Convert Terraform to AWS SAM

**Why?**

Good question, because you have been told to do so? ¯\_(ツ)_/¯

# Usage

```
usage: tf2sam.py [-h] {transform,t} ...

Transform Terraform to AWS SAM

positional arguments:
  {transform,t}
    transform (t)
                 transform terraform .tf file to sam format

optional arguments:
  -h, --help     show this help message and exit
```

To transform:

```
usage: tf2sam.py transform [-h] [-p] file

transform terraform .tf file to sam format

positional arguments:
  file              path to terraform file

optional arguments:
  -h, --help        show this help message and exit
  -p, --print-yaml  print generated yaml instead of writing to file (default: False)
```

**NOTE:** Its highly recommended that you run cfn-lint or similar on generated cloudformation

# Importing Existing Resources

See https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/resource-import.html

# Apex

For terraform using (now discontinued) apex, see https://github.com/apex/apex