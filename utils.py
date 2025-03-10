import xml.etree.ElementTree as ET

def xml_to_dict(xml_string):
    def strip_namespace(tag):
        """Remove namespace from the tag name."""
        return tag.split("}")[-1] if "}" in tag else tag

    def parse_element(element):
        parsed_data = {}
        children = list(element)

        # Check if all children have the same tag (implying a list)
        child_tags = [strip_namespace(child.tag) for child in children]
        list_tags = ["players"]
        is_list = strip_namespace(element.tag) in list_tags or len(set(child_tags)) == 1 and len(children) > 1 # TODO: 

        # Convert child elements into dictionary keys
        if is_list:
            return [parse_element(child) for child in children]  # Return a list directly
        else:
            for child in children:
                tag = strip_namespace(child.tag)
                child_data = parse_element(child)

                # Handle multiple children with the same tag by storing them as lists
                if tag in parsed_data:
                    if not isinstance(parsed_data[tag], list):
                        parsed_data[tag] = [parsed_data[tag]]
                    parsed_data[tag].append(child_data)
                else:
                    parsed_data[tag] = child_data

        # If the element has text content, add it
        text = element.text.strip() if element.text else ""
        if text and not parsed_data:
            return text  # Return text if no nested structure

        return parsed_data or text  # Return text if no nested structure

    root = ET.fromstring(xml_string)
    return parse_element(root)