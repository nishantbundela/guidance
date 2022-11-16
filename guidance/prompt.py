import re
import html
import ast
from . import generators

# TODO: record the string as we build it so we can print it our later to the user
#       with nive highlighting of the parts that are generated by the LM and each
#       variable that is used

# TODO: if we request the log probs for the text then we should return html that
#       colors the (opacity of orignal color?) text based on the log prob of each
#       token, and allows the user to click on the text to see the log prob of each
#       token (like the playgound, but something you can use in a notebook)

# TODO: add support for the insert mode of GPT3 (to guide a generation to a given end)

# TODO: allow for backreferences to a previous "get" call variable

class PromptCompletion:
    ''' Represents the result of an executed prompt.
    '''
    def __init__(self, results, variables, completed_text, completed_text_html, prompt):
        self.results = results
        self.variables = variables
        self.completed_text = completed_text
        self.completed_text_html = completed_text_html
        self.prompt = prompt

    def __getitem__(self, key):
        return self.results[key]

    def __repr__(self):
        return self.completed_text

    def _repr_html_(self):
        return self.completed_text_html


class Prompt:
    ''' A prompt template that can be compiled and executed to generate a PromptCompletion result.
    '''

    def __init__(self, prompt, generator=None):
        self.prompt = prompt
        self.generator = generator

        # default to an OpenAI generator
        if self.generator is None:
            self.generator = generators.OpenAI()
    
    def __call__(self, variables, execution_method="fixed_prefix"):

        if execution_method == "fixed_prefix":
            out, display_out = parse(self.prompt, self.generator, variables)
            fixed_prefix = re.sub(r'\{\{get .*', '', out, flags=re.DOTALL)
            output_template_escaped = re.escape(out[len(fixed_prefix):])

            out2 = self.generator(fixed_prefix, max_tokens=250)

            pattern = re.sub(r'\\\{\\\{get\\ ([^\\]+)\\\}\\\}', r'(?P<\1>.*)', output_template_escaped)
            match = re.match(pattern, out2["choices"][0]["text"], flags=re.DOTALL)
            if match is None:
                return None
            else:
                captures = match.groupdict()
                for k, v in captures.items():
                    out = out.replace(f"{{{{get {k}}}}}", v)
                    # v = f"<span style='background-color: rgb(0, 165, 0, 0.25); display: inline;' title='get {k}'>" + v + "</span>"
                    display_out = display_out.replace(f"{{{{get {k}}}}}", v)
                display_out = html.escape(display_out)
                display_out = re.sub(r"__VARSPAN_START_([^\$]*)\$___", r"<span style='background-color: rgb(0, 138.56128016, 250.76166089, 0.25); display: inline;' title='{{\1}}'>", display_out)
                display_out = display_out.replace("__VARSPAN_END___", "</span>")
                display_out = re.sub(r"__GETSPAN_START_([^\$]*)\$___", r"<span style='background-color: rgb(0, 165, 0, 0.25); display: inline;' title='{{\1}}'>", display_out)
                display_out = display_out.replace("__GETSPAN_END___", "</span>")
                display_out = display_out.replace("__LOOP_DIVIDER___", "<div style='border-left: 1px dashed rgb(0, 0, 0, .2); border-top: 0px solid rgb(0, 0, 0, .2); margin-right: -4px; display: inline; width: 4px; height: 24px;'></div>")
                # display_out = display_out.replace("__LOOP_END___", "<div style='border-right: 1px solid rgb(0, 0, 0, .2); border-top: 0px solid rgb(0, 0, 0, .2); margin-left: -4px; display: inline; width: 4px; height: 24px;'></div>")
                display_out = "<pre style='padding: 7px; border-radius: 4px; background: white; white-space: pre-wrap; font-family: ColfaxAI, Arial; font-size: 16px; line-height: 24px; color: #000'>"+display_out+"</pre>"
                # print("display_out", display_out)
                return PromptCompletion(match.groupdict(), variables, out, display_out, self)

span_style = "background-color: rgb(0, 138.03019826, 250.62656482, 0.25); display: inline;"

def parse(prompt, generator=None, variables={}, unresolved_gets={}, prefix=""):
    # print("prompt", prompt)
    tag_open = False
    tag_start = 0
    tag_out_start = 0
    out = ""
    display_out = ""
    i = 0
    in_recurse_group = False
    recurse_group_start = 0
    recurse_group_name = ""
    recurse_group_args = []
    recurse_group_depth = 0
    for_item_name = ""

    # walk through the prompt character by character
    while i < len(prompt):

        # find tag starts
        if prompt[i:i+2] == '{{':
            tag_open = True
            tag_start = i+2
            tag_out_start = len(out)
            i += 2

        # process tags on tag ends
        elif prompt[i:i+2] == '}}':
            tag_open = False
            # tag_end = i
            tag_name = prompt[tag_start:i]
            i += 2

            # if we are in a recurse group then we need to just skip over all the internal content to find the closing tag
            if in_recurse_group:
                if tag_name.startswith("#"):
                    raw_name = tag_name.split()[0][1:]
                    if raw_name == recurse_group_name:
                        recurse_group_depth += 1
                elif tag_name.startswith("/"):
                    raw_name = tag_name[1:]
                    if raw_name == recurse_group_name:
                        recurse_group_depth -= 1
                        if recurse_group_depth == 0:
                            if raw_name == "each":
                                items = variables.get(recurse_group_args[0], [])
                                for j, var in enumerate(items):
                                    # print("VAR", var)
                                    o, do = parse(prompt[recurse_group_start:tag_start-2], generator, variables | {"this": var} | {"@last": j == len(items)-1, "@first": j == 0, "@index": j}, prefix=prefix+out)
                                    out += o
                                    display_out += do
                            elif raw_name == "for":
                                assert recurse_group_args[1] == "in"
                                items = parse_var_exp(recurse_group_args[2], variables, [])
                                # items = variables.get(recurse_group_args[2], [])
                                item_name = recurse_group_args[0]
                                for j, var in enumerate(items):
                                    display_out += "__LOOP_DIVIDER___"
                                    o, do = parse(prompt[recurse_group_start:tag_start-2], generator, variables | {item_name: var} | {"@last": j == len(items)-1, "@first": j == 0, "@index": j}, prefix=prefix+out)
                                    out += o
                                    display_out += do
                                display_out += "__LOOP_DIVIDER___"
                            elif raw_name == "if":
                                if variables.get(recurse_group_args[0], False):
                                    o, do = parse(prompt[recurse_group_start:tag_start-2], generator, variables, prefix=prefix+out)
                                    out += o
                                    display_out += do
                            elif raw_name == "unless":
                                if not variables.get(recurse_group_args[0], False):
                                    o, do = parse(prompt[recurse_group_start:tag_start-2], generator, variables, prefix=prefix+out)
                                    out += o
                                    display_out += do
                            in_recurse_group = False
                            recurse_group_name = ""
                            recurse_group_start = 0
            
            # if we are not in a recurse group then we need to process the tag
            else:
                if tag_name.startswith("#"):
                    raw_name = tag_name.split()[0][1:]
                    in_recurse_group = True
                    recurse_group_start = i
                    recurse_group_name = raw_name
                    recurse_group_args = tag_name.split()[1:]
                    recurse_group_depth = 1
                    
                elif tag_name.startswith("/"):
                    raise Exception("Closing tag without opening tag:", tag_name)
                else:
                    parts = tag_name.split()
                    if len(parts) == 1:
                        val = str(parse_var_exp(tag_name, variables, ""))
                        out += val
                        display_out += "__VARSPAN_START_"+tag_name+"$___" + val + "__VARSPAN_END___"

                    elif len(parts) >= 2:
                        if parts[0] == "get":
                            if len(parts) == 2:
                                stop_sequences = None
                            elif parts[2] == "without":
                                pattern = ast.literal_eval(parts[3])
                                if re.escape(pattern) ==pattern:
                                    stop_sequences = [pattern]
                                else:
                                    raise Exception("stop sequence must be a literal string, support for REGEX stops is TODO")
                            else:
                                raise Exception("Unknown get option:", parts[2])
                            
                            gen_obj = generator(out, stop=stop_sequences)
                            gen_text = gen_obj["choices"][0]["text"]
                            out += gen_text
                            variables[parts[1]] = gen_text
                            # unresolved_gets[parts[1]] = (tag_start, parts[2:])
                            # print("Call the LM with:\n", out)
                            # out += "{{" + tag_name + "}}" # TODO: need to record so we can enable later dependencies on the answer
                            display_out += "__GETSPAN_START_"+tag_name+"$___" + gen_text + "__GETSPAN_END___"
            # print("===", tag_name)
        elif not tag_open and not in_recurse_group:
            out += prompt[i]
            display_out += prompt[i]
            i += 1
        else:
            i += 1
    if in_recurse_group:
        raise Exception("Unclosed tag:", recurse_group_name)
    return out, display_out

def parse_var_exp(exp, variables, default):
    if "(" in exp: # TODO: support . in function args and names
        name, args = exp.split("(", 1)
        val = variables[name](*[variables[a.strip()] for a in args[:-1].split(",")]) 
    elif "." in exp:
        var_name, var_attr = exp.split(".", 2)
        val = variables.get(var_name, {}).get(var_attr, default)
    else:
        val = variables.get(exp, default)
    return val